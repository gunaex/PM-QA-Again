from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_project_db
from ..auth import require_tester, require_admin, require_project_access

router = APIRouter(
    prefix="/api/{slug}/cycles/{cycle_id}/results", tags=["cycle-results"], dependencies=[Depends(require_project_access)]
)


def _get_cycle(db: Session, cycle_id: int) -> models.TestCycle:
    cycle = db.query(models.TestCycle).filter(models.TestCycle.id == cycle_id).first()
    if not cycle:
        raise HTTPException(status_code=404, detail="Cycle not found")
    return cycle


def _to_list_out(result: models.CycleTestResult, case: models.TestCase) -> schemas.CycleTestResultListOut:
    out = schemas.CycleTestResultListOut.model_validate(result)
    out.checkpoint_code = case.checkpoint_code
    out.case_title = case.title
    out.case_priority = case.priority
    return out


def _to_out(result: models.CycleTestResult, case: models.TestCase) -> schemas.CycleTestResultOut:
    out = schemas.CycleTestResultOut.model_validate(result)
    out.checkpoint_code = case.checkpoint_code
    out.case_title = case.title
    out.case_priority = case.priority
    out.case_action_md = case.action_md
    out.case_expected_result_md = case.expected_result_md
    out.case_setup_md = case.setup_md
    out.case_validation_md = case.validation_md
    return out


def _get_result_with_case(db: Session, cycle_id: int, result_id: int) -> tuple[models.CycleTestResult, models.TestCase]:
    result = (
        db.query(models.CycleTestResult)
        .filter(models.CycleTestResult.id == result_id, models.CycleTestResult.cycle_id == cycle_id)
        .first()
    )
    if not result:
        raise HTTPException(status_code=404, detail="Result not found")
    case = db.query(models.TestCase).filter(models.TestCase.id == result.test_case_id).first()
    return result, case


@router.get("", response_model=list[schemas.CycleTestResultListOut])
def list_results(slug: str, cycle_id: int, db: Session = Depends(get_project_db)):
    _get_cycle(db, cycle_id)
    results = (
        db.query(models.CycleTestResult).filter(models.CycleTestResult.cycle_id == cycle_id).order_by(models.CycleTestResult.id).all()
    )
    case_ids = [r.test_case_id for r in results]
    case_by_id = {c.id: c for c in db.query(models.TestCase).filter(models.TestCase.id.in_(case_ids)).all()}
    return [_to_list_out(r, case_by_id[r.test_case_id]) for r in results]


@router.get("/{result_id}", response_model=schemas.CycleTestResultOut)
def get_result(slug: str, cycle_id: int, result_id: int, db: Session = Depends(get_project_db)):
    _get_cycle(db, cycle_id)
    result, case = _get_result_with_case(db, cycle_id, result_id)
    return _to_out(result, case)


@router.put("/{result_id}", response_model=schemas.CycleTestResultOut)
def update_result(
    slug: str,
    cycle_id: int,
    result_id: int,
    payload: schemas.CycleTestResultUpdate,
    db: Session = Depends(get_project_db),
    user: models.User = Depends(require_tester),
):
    cycle = _get_cycle(db, cycle_id)
    if cycle.status == "LOCKED":
        raise HTTPException(status_code=400, detail="Cycle is LOCKED — results cannot be mutated. An admin must /reopen it first.")

    result, case = _get_result_with_case(db, cycle_id, result_id)

    if payload.status not in models.RESULT_STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {models.RESULT_STATUSES}")
    if payload.status == "FAIL" and not (payload.actual_result_md or "").strip():
        raise HTTPException(status_code=400, detail="FAIL requires an actual result")
    if payload.status == "BLOCKED" and not (payload.blocked_reason or "").strip():
        raise HTTPException(status_code=400, detail="BLOCKED requires a blocked_reason")
    if payload.status == "NOT_APPLICABLE" and not (payload.na_reason or "").strip():
        raise HTTPException(status_code=400, detail="NOT_APPLICABLE requires a na_reason")
    if payload.status == "PASS" and cycle.require_evidence_for_pass:
        has_evidence = (
            db.query(models.EvidenceItem)
            .filter(models.EvidenceItem.cycle_test_result_id == result_id, models.EvidenceItem.status == "ACTIVE")
            .first()
        )
        if not has_evidence:
            raise HTTPException(
                status_code=400,
                detail="PASS requires at least one evidence item (this cycle's require_evidence_for_pass is enabled)",
            )

    changed = (
        result.status != payload.status
        or result.actual_result_md != payload.actual_result_md
        or result.blocked_reason != payload.blocked_reason
        or result.na_reason != payload.na_reason
    )

    if not result.started_at:
        result.started_at = datetime.utcnow()
    result.status = payload.status
    result.actual_result_md = payload.actual_result_md
    result.blocked_reason = payload.blocked_reason
    result.na_reason = payload.na_reason
    if payload.defect_reference is not None:
        result.defect_reference = payload.defect_reference
    if payload.assigned_tester_email is not None:
        result.assigned_tester_email = payload.assigned_tester_email

    if payload.status != "NOT_RUN":
        result.executed_at = datetime.utcnow()
        result.executed_by = user.email
    if payload.status == "NOT_APPLICABLE":
        result.review_status = "UNREVIEWED"  # (re-)enters the admin-approval queue every time it's set to N/A

    if changed:
        result.result_revision_no += 1
        db.add(
            models.CycleResultHistory(
                cycle_test_result_id=result.id,
                result_revision_no=result.result_revision_no,
                status=result.status,
                actual_result_md=result.actual_result_md,
                blocked_reason=result.blocked_reason,
                na_reason=result.na_reason,
                changed_by=user.email,
                change_source="HUMAN",
            )
        )

    # First real execution nudges a READY cycle into IN_PROGRESS — a
    # convenience, not a hard rule; testers/admins can still set status
    # explicitly via PUT /cycles/{id}.
    if cycle.status == "READY" and payload.status != "NOT_RUN":
        cycle.status = "IN_PROGRESS"
        cycle.started_at = cycle.started_at or datetime.utcnow()

    db.commit()
    db.refresh(result)
    return _to_out(result, case)


@router.post("/{result_id}/review", response_model=schemas.CycleTestResultOut)
def review_result(
    slug: str,
    cycle_id: int,
    result_id: int,
    payload: schemas.CycleResultReviewRequest,
    db: Session = Depends(get_project_db),
    user: models.User = Depends(require_admin),
):
    """Admin approval for NOT_APPLICABLE results (rebuild prompt §12:
    "NOT APPLICABLE must require a written reason and Admin approval").
    Scoped to NOT_APPLICABLE only — not a general-purpose review of every
    result, which the spec doesn't ask for."""
    _get_cycle(db, cycle_id)
    result, case = _get_result_with_case(db, cycle_id, result_id)
    if result.status != "NOT_APPLICABLE":
        raise HTTPException(status_code=400, detail="Only a NOT_APPLICABLE result can be reviewed")
    if payload.review_status not in ("ACCEPTED", "CHANGES_REQUESTED"):
        raise HTTPException(status_code=400, detail="review_status must be ACCEPTED or CHANGES_REQUESTED")

    result.review_status = payload.review_status
    result.reviewed_by = user.email
    result.reviewed_at = datetime.utcnow()
    db.commit()
    db.refresh(result)
    return _to_out(result, case)


@router.get("/{result_id}/history", response_model=list[schemas.CycleResultHistoryOut])
def get_result_history(slug: str, cycle_id: int, result_id: int, db: Session = Depends(get_project_db)):
    _get_cycle(db, cycle_id)
    _get_result_with_case(db, cycle_id, result_id)
    return (
        db.query(models.CycleResultHistory)
        .filter(models.CycleResultHistory.cycle_test_result_id == result_id)
        .order_by(models.CycleResultHistory.result_revision_no)
        .all()
    )
