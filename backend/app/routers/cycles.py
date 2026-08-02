from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_project_db
from ..activity import log_change
from ..auth import get_current_user, require_tester, require_admin

router = APIRouter(prefix="/api/{slug}/cycles", tags=["cycles"], dependencies=[Depends(get_current_user)])


def most_recently_used_environment(db: Session, default: str = "production") -> str:
    """"Default to the most recently used value" -- reuses the existing
    TestCycle history directly rather than adding a new preference
    table: the most recently *created* cycle's own environment field,
    project-wide."""
    latest = db.query(models.TestCycle.environment).order_by(models.TestCycle.created_at.desc()).first()
    return latest[0] if latest else default


def create_cycle_with_snapshot(
    db: Session,
    user_email: str,
    *,
    suite_id: int,
    script_revision_id: int,
    name: str,
    environment: str,
    require_evidence_for_pass: bool,
    is_system_generated: bool = False,
    only_case_ids: list[int] | None = None,
    release_version: str | None = None,
    target_base_url: str | None = None,
    cycle_code: str | None = None,
) -> models.TestCycle:
    """Shared snapshot-creation logic behind POST /cycles, Run Now, and
    Rerun -- exactly one code path creates a TestCycle + its NOT_RUN
    CycleTestResult rows, so every entry point gets the same
    immutable-snapshot guarantee. `only_case_ids`, when given, snapshots
    just that subset of the revision's cases (used by "rerun FAIL/
    BLOCKED only" and "rerun selected cases") -- still a real, complete
    TestCycle/CycleTestResult snapshot, just scoped to fewer cases,
    never a parallel model."""
    cases = db.query(models.TestCase).filter(models.TestCase.revision_id == script_revision_id).all()
    if only_case_ids is not None:
        allowed = set(only_case_ids)
        cases = [c for c in cases if c.id in allowed]
    if not cases:
        raise HTTPException(status_code=400, detail="Cannot create a cycle with no test cases")

    cycle = models.TestCycle(
        suite_id=suite_id,
        script_revision_id=script_revision_id,
        cycle_code=cycle_code,
        name=name,
        environment=environment,
        release_version=release_version,
        target_base_url=target_base_url,
        status="READY",
        require_evidence_for_pass=require_evidence_for_pass,
        is_system_generated=is_system_generated,
        created_by=user_email,
    )
    db.add(cycle)
    db.flush()
    for case in cases:
        db.add(models.CycleTestResult(cycle_id=cycle.id, test_case_id=case.id, status="NOT_RUN"))
    return cycle


def _result_counts(db: Session, cycle_id: int) -> schemas.ResultCounts:
    rows = (
        db.query(models.CycleTestResult.status, models.CycleTestResult.id)
        .filter(models.CycleTestResult.cycle_id == cycle_id)
        .all()
    )
    counts = schemas.ResultCounts()
    for status, _id in rows:
        setattr(counts, status, getattr(counts, status) + 1)
    return counts


def _to_out(db: Session, cycle: models.TestCycle) -> schemas.TestCycleOut:
    out = schemas.TestCycleOut.model_validate(cycle)
    out.result_counts = _result_counts(db, cycle.id)
    return out


@router.get("", response_model=list[schemas.TestCycleOut])
def list_cycles(slug: str, include_system_generated: bool = False, db: Session = Depends(get_project_db)):
    q = db.query(models.TestCycle)
    if not include_system_generated:
        q = q.filter(models.TestCycle.is_system_generated.is_(False))
    cycles = q.order_by(models.TestCycle.created_at.desc()).all()
    # One grouped query for every cycle's result counts instead of a
    # per-cycle query (was N+1 — see docs/PERFORMANCE.md).
    counts_by_cycle: dict[int, schemas.ResultCounts] = {c.id: schemas.ResultCounts() for c in cycles}
    if cycles:
        rows = (
            db.query(models.CycleTestResult.cycle_id, models.CycleTestResult.status, func.count())
            .filter(models.CycleTestResult.cycle_id.in_(counts_by_cycle.keys()))
            .group_by(models.CycleTestResult.cycle_id, models.CycleTestResult.status)
            .all()
        )
        for cycle_id, status, n in rows:
            setattr(counts_by_cycle[cycle_id], status, n)

    out = []
    for c in cycles:
        item = schemas.TestCycleOut.model_validate(c)
        item.result_counts = counts_by_cycle[c.id]
        out.append(item)
    return out


@router.post("", response_model=schemas.TestCycleOut)
def create_cycle(
    slug: str,
    payload: schemas.TestCycleCreate,
    db: Session = Depends(get_project_db),
    user: models.User = Depends(require_tester),
):
    revision = db.query(models.ScriptRevision).filter(models.ScriptRevision.id == payload.script_revision_id).first()
    if not revision:
        raise HTTPException(status_code=404, detail="Script revision not found")
    if revision.suite_id != payload.suite_id:
        raise HTTPException(status_code=400, detail="script_revision_id does not belong to suite_id")
    if revision.status != "PUBLISHED":
        raise HTTPException(status_code=400, detail=f"A cycle must reference a PUBLISHED revision (current status: {revision.status})")

    # Snapshot: one NOT_RUN result per case in *this exact* revision.
    # Never re-derived later — a subsequent publish of a newer revision
    # must never change this cycle (rebuild prompt §12).
    cycle = create_cycle_with_snapshot(
        db, user.email,
        suite_id=payload.suite_id, script_revision_id=payload.script_revision_id,
        name=payload.name, environment=payload.environment,
        require_evidence_for_pass=payload.require_evidence_for_pass,
        release_version=payload.release_version, target_base_url=payload.target_base_url,
        cycle_code=payload.cycle_code,
    )

    db.commit()
    db.refresh(cycle)
    return _to_out(db, cycle)


@router.get("/{cycle_id}", response_model=schemas.TestCycleOut)
def get_cycle(slug: str, cycle_id: int, db: Session = Depends(get_project_db)):
    cycle = db.query(models.TestCycle).filter(models.TestCycle.id == cycle_id).first()
    if not cycle:
        raise HTTPException(status_code=404, detail="Cycle not found")
    return _to_out(db, cycle)


@router.put("/{cycle_id}", response_model=schemas.TestCycleOut)
def update_cycle(
    slug: str,
    cycle_id: int,
    payload: schemas.TestCycleUpdate,
    db: Session = Depends(get_project_db),
    user: models.User = Depends(require_tester),
):
    cycle = db.query(models.TestCycle).filter(models.TestCycle.id == cycle_id).first()
    if not cycle:
        raise HTTPException(status_code=404, detail="Cycle not found")
    if cycle.status == "LOCKED":
        raise HTTPException(status_code=400, detail="Cycle is LOCKED — use /reopen (admin) before editing")

    updates = payload.model_dump(exclude_unset=True)
    if "status" in updates:
        if updates["status"] == "LOCKED":
            raise HTTPException(status_code=400, detail="Use POST /cycles/{id}/lock to lock a cycle")
        if updates["status"] not in models.CYCLE_STATUSES:
            raise HTTPException(status_code=400, detail=f"status must be one of {models.CYCLE_STATUSES}")

    for key, value in updates.items():
        setattr(cycle, key, value)
    db.commit()
    db.refresh(cycle)
    return _to_out(db, cycle)


@router.post("/{cycle_id}/lock", response_model=schemas.TestCycleOut)
def lock_cycle(
    slug: str,
    cycle_id: int,
    db: Session = Depends(get_project_db),
    user: models.User = Depends(require_admin),
):
    cycle = db.query(models.TestCycle).filter(models.TestCycle.id == cycle_id).first()
    if not cycle:
        raise HTTPException(status_code=404, detail="Cycle not found")
    if cycle.status == "LOCKED":
        raise HTTPException(status_code=400, detail="Cycle is already locked")

    cycle.status = "LOCKED"
    cycle.locked_at = datetime.utcnow()
    cycle.locked_by = user.email
    if not cycle.finished_at:
        cycle.finished_at = cycle.locked_at
    db.commit()
    db.refresh(cycle)
    return _to_out(db, cycle)


@router.post("/{cycle_id}/reopen", response_model=schemas.TestCycleOut)
def reopen_cycle(
    slug: str,
    cycle_id: int,
    payload: schemas.CycleReopenRequest,
    db: Session = Depends(get_project_db),
    user: models.User = Depends(require_admin),
):
    """Administrative reopen — requires a reason and is audit-logged
    (rebuild prompt §11: "any administrative reopen must require reason
    and append an audit record")."""
    cycle = db.query(models.TestCycle).filter(models.TestCycle.id == cycle_id).first()
    if not cycle:
        raise HTTPException(status_code=404, detail="Cycle not found")
    if cycle.status != "LOCKED":
        raise HTTPException(status_code=400, detail="Only a LOCKED cycle can be reopened")
    if not payload.reason.strip():
        raise HTTPException(status_code=400, detail="A reason is required to reopen a locked cycle")

    log_change(db, "cycle", cycle_id, "status", "LOCKED", f"IN_PROGRESS (reopened: {payload.reason})", user.email)
    cycle.status = "IN_PROGRESS"
    cycle.locked_at = None
    cycle.locked_by = None
    cycle.finished_at = None
    db.commit()
    db.refresh(cycle)
    return _to_out(db, cycle)


@router.post("/{cycle_id}/rerun", response_model=schemas.TestCycleOut)
def rerun_cycle(
    slug: str,
    cycle_id: int,
    payload: schemas.RerunCycleRequest,
    db: Session = Depends(get_project_db),
    user: models.User = Depends(require_tester),
):
    """Creates a brand-new TestCycle (a fresh, real snapshot against the
    exact same script_revision_id) — never mutates or re-derives the
    source cycle, preserving full historical separation. Three modes:
    - "all": every case the source cycle covered.
    - "fail_blocked": only cases whose latest result in the source cycle
      is FAIL or BLOCKED.
    - "selected": exactly the case_ids the caller supplies (must have
      been part of the source cycle).
    """
    source = db.query(models.TestCycle).filter(models.TestCycle.id == cycle_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="Cycle not found")

    if payload.mode not in ("all", "fail_blocked", "selected"):
        raise HTTPException(status_code=400, detail="mode must be one of: all, fail_blocked, selected")

    source_results = (
        db.query(models.CycleTestResult).filter(models.CycleTestResult.cycle_id == cycle_id).all()
    )
    source_case_ids = {r.test_case_id for r in source_results}

    if payload.mode == "all":
        only_case_ids = None  # every case in the revision, matching the source cycle's own full scope
    elif payload.mode == "fail_blocked":
        only_case_ids = [r.test_case_id for r in source_results if r.status in ("FAIL", "BLOCKED")]
        if not only_case_ids:
            raise HTTPException(status_code=400, detail="No FAIL or BLOCKED cases in this cycle to rerun")
    else:  # selected
        if not payload.case_ids:
            raise HTTPException(status_code=400, detail="case_ids is required for mode=selected")
        only_case_ids = [cid for cid in payload.case_ids if cid in source_case_ids]
        if not only_case_ids:
            raise HTTPException(status_code=400, detail="None of the given case_ids were part of the source cycle")

    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    mode_label = {"all": "Rerun", "fail_blocked": "Rerun (FAIL/BLOCKED only)", "selected": "Rerun (selected cases)"}[payload.mode]
    new_cycle = create_cycle_with_snapshot(
        db, user.email,
        suite_id=source.suite_id, script_revision_id=source.script_revision_id,
        name=f"{source.name} — {mode_label} {timestamp}",
        environment=source.environment,
        require_evidence_for_pass=source.require_evidence_for_pass,
        is_system_generated=source.is_system_generated,
        only_case_ids=only_case_ids,
        release_version=source.release_version, target_base_url=source.target_base_url,
    )
    db.commit()
    db.refresh(new_cycle)
    return _to_out(db, new_cycle)
