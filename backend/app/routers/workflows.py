"""HYB-1: workflow definitions, immutable-once-published revisions,
ordered steps, and test-case links. Mirrors the suites/revisions/cases
pattern deliberately -- same DRAFT->PUBLISHED->SUPERSEDED lifecycle,
same "mutate only while DRAFT" rule, same clone-for-correction. See
docs/hybrid/HYB-1-GAP-ANALYSIS-REFRESH.md for the design decisions."""
import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_project_db
from ..activity import log_change, log_changes
from ..auth import get_current_user, require_tester, require_admin

router = APIRouter(prefix="/api/{slug}/workflows", tags=["workflows"], dependencies=[Depends(get_current_user)])

# A sensitive step's input_value must be a variable placeholder, never a
# literal value -- this is what "configure a sensitive variable without
# persisting its real value" means at the data-model level, enforced
# server-side rather than left to UI discipline alone.
_VARIABLE_REF = re.compile(r"^\$\{[A-Z][A-Z0-9_]*\}$")

_LOCATOR_REQUIRED_TYPES = {
    "CLICK", "FILL", "SELECT", "CHECK", "UNCHECK", "PRESS_KEY", "WAIT_FOR_ELEMENT", "ASSERT_VISIBLE",
}


def _get_workflow(db: Session, workflow_id: int) -> models.WorkflowDefinition:
    obj = db.query(models.WorkflowDefinition).filter(models.WorkflowDefinition.id == workflow_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return obj


def _get_revision(db: Session, workflow_id: int, revision_id: int) -> models.WorkflowRevision:
    obj = (
        db.query(models.WorkflowRevision)
        .filter(models.WorkflowRevision.id == revision_id, models.WorkflowRevision.workflow_id == workflow_id)
        .first()
    )
    if not obj:
        raise HTTPException(status_code=404, detail="Workflow revision not found")
    return obj


def _require_draft(revision: models.WorkflowRevision):
    if revision.status != "DRAFT":
        raise HTTPException(
            status_code=400,
            detail=f"Workflow steps/links can only be edited while the revision is DRAFT (current status: {revision.status})",
        )


def _validate_step_fields(step_type: str, fields: dict):
    if step_type not in models.WORKFLOW_STEP_TYPES:
        raise HTTPException(status_code=400, detail=f"step_type must be one of {models.WORKFLOW_STEP_TYPES}")

    locator_strategy = fields.get("locator_strategy")
    locator_value = fields.get("locator_value")
    if step_type in _LOCATOR_REQUIRED_TYPES:
        if not locator_strategy or not locator_value:
            raise HTTPException(status_code=400, detail=f"{step_type} requires locator_strategy and locator_value")
        if locator_strategy not in models.LOCATOR_STRATEGIES:
            raise HTTPException(status_code=400, detail=f"locator_strategy must be one of {models.LOCATOR_STRATEGIES}")

    if step_type == "NAVIGATE" and not (fields.get("input_value") or "").strip():
        raise HTTPException(status_code=400, detail="NAVIGATE requires input_value (a URL)")

    if step_type in ("FILL", "SELECT") and not (fields.get("input_value") or "").strip():
        raise HTTPException(status_code=400, detail=f"{step_type} requires input_value")

    if step_type in ("ASSERT_TEXT", "ASSERT_URL") and not (fields.get("expected_value") or "").strip():
        raise HTTPException(status_code=400, detail=f"{step_type} requires expected_value")

    if step_type == "MANUAL_CHECKPOINT" and not (fields.get("checkpoint_instructions") or "").strip():
        raise HTTPException(status_code=400, detail="MANUAL_CHECKPOINT requires checkpoint_instructions")

    if step_type == "WAIT":
        raw = (fields.get("input_value") or "").strip()
        if not raw.isdigit() or int(raw) <= 0:
            raise HTTPException(status_code=400, detail="WAIT requires input_value to be a positive number of milliseconds")

    repeat_count = fields.get("repeat_count")
    if repeat_count is not None and (not isinstance(repeat_count, int) or repeat_count < 1):
        raise HTTPException(status_code=400, detail="repeat_count must be a positive integer (or omitted)")

    # The sensitive-value rule: never a literal, always "${VAR_NAME}".
    if fields.get("is_sensitive"):
        value = fields.get("input_value") or ""
        if not _VARIABLE_REF.match(value):
            raise HTTPException(
                status_code=400,
                detail='A sensitive step\'s input_value must be a variable placeholder like "${SECRET_LOGIN_PASSWORD}", '
                "never a literal value.",
            )

    if fields.get("evidence_policy") and fields["evidence_policy"] not in models.EVIDENCE_POLICIES:
        raise HTTPException(status_code=400, detail=f"evidence_policy must be one of {models.EVIDENCE_POLICIES}")


# ---------- Workflow definitions ----------


@router.get("", response_model=list[schemas.WorkflowDefinitionOut])
def list_workflows(slug: str, db: Session = Depends(get_project_db)):
    workflows = db.query(models.WorkflowDefinition).order_by(models.WorkflowDefinition.created_at.desc()).all()
    out = []
    for w in workflows:
        item = schemas.WorkflowDefinitionOut.model_validate(w)
        published = (
            db.query(models.WorkflowRevision)
            .filter(models.WorkflowRevision.workflow_id == w.id, models.WorkflowRevision.status == "PUBLISHED")
            .first()
        )
        if published:
            item.published_revision_id = published.id
            item.published_revision_label = published.revision_label
        out.append(item)
    return out


@router.post("", response_model=schemas.WorkflowDefinitionOut)
def create_workflow(
    slug: str,
    payload: schemas.WorkflowDefinitionCreate,
    db: Session = Depends(get_project_db),
    user: models.User = Depends(require_tester),
):
    obj = models.WorkflowDefinition(name=payload.name, description=payload.description, created_by=user.email)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("/{workflow_id}", response_model=schemas.WorkflowDefinitionOut)
def get_workflow(slug: str, workflow_id: int, db: Session = Depends(get_project_db)):
    return _get_workflow(db, workflow_id)


# ---------- Workflow revisions ----------


@router.get("/{workflow_id}/revisions", response_model=list[schemas.WorkflowRevisionOut])
def list_revisions(slug: str, workflow_id: int, db: Session = Depends(get_project_db)):
    _get_workflow(db, workflow_id)
    return (
        db.query(models.WorkflowRevision)
        .filter(models.WorkflowRevision.workflow_id == workflow_id)
        .order_by(models.WorkflowRevision.revision_number_sort.desc())
        .all()
    )


@router.post("/{workflow_id}/revisions", response_model=schemas.WorkflowRevisionOut)
def create_revision(
    slug: str,
    workflow_id: int,
    payload: schemas.WorkflowRevisionCreate,
    db: Session = Depends(get_project_db),
    user: models.User = Depends(require_tester),
):
    _get_workflow(db, workflow_id)
    existing = (
        db.query(models.WorkflowRevision)
        .filter(models.WorkflowRevision.workflow_id == workflow_id, models.WorkflowRevision.revision_label == payload.revision_label)
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="A revision with that label already exists for this workflow")
    max_sort = (
        db.query(models.WorkflowRevision.revision_number_sort)
        .filter(models.WorkflowRevision.workflow_id == workflow_id)
        .order_by(models.WorkflowRevision.revision_number_sort.desc())
        .first()
    )
    next_sort = (max_sort[0] + 1) if max_sort else 1
    obj = models.WorkflowRevision(
        workflow_id=workflow_id,
        revision_label=payload.revision_label,
        revision_number_sort=next_sort,
        status="DRAFT",
        change_summary=payload.change_summary,
        created_by=user.email,
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("/{workflow_id}/revisions/{revision_id}", response_model=schemas.WorkflowRevisionOut)
def get_revision(slug: str, workflow_id: int, revision_id: int, db: Session = Depends(get_project_db)):
    return _get_revision(db, workflow_id, revision_id)


# Publishing is ADMIN-only, matching revisions.py's own rule for test
# scripts -- an unreviewed draft becoming an immutable, runnable
# automation asset warrants the same admin gate.
@router.post("/{workflow_id}/revisions/{revision_id}/publish", response_model=schemas.WorkflowRevisionOut)
def publish_revision(
    slug: str,
    workflow_id: int,
    revision_id: int,
    db: Session = Depends(get_project_db),
    user: models.User = Depends(require_admin),
):
    obj = _get_revision(db, workflow_id, revision_id)
    if obj.status != "DRAFT":
        raise HTTPException(status_code=400, detail=f"Only a DRAFT revision can be published (current status: {obj.status})")

    steps = (
        db.query(models.WorkflowStep)
        .filter(models.WorkflowStep.revision_id == revision_id, models.WorkflowStep.enabled.is_(True))
        .all()
    )
    if not steps:
        raise HTTPException(status_code=400, detail="Cannot publish a revision with no enabled steps")
    for step in steps:
        _validate_step_fields(
            step.step_type,
            {
                "locator_strategy": step.locator_strategy,
                "locator_value": step.locator_value,
                "input_value": step.input_value,
                "expected_value": step.expected_value,
                "checkpoint_instructions": step.checkpoint_instructions,
                "is_sensitive": step.is_sensitive,
                "evidence_policy": step.evidence_policy,
            },
        )

    obj.status = "PUBLISHED"
    obj.published_at = datetime.utcnow()
    obj.published_by = user.email

    if obj.supersedes_revision_id:
        prior = db.query(models.WorkflowRevision).filter(models.WorkflowRevision.id == obj.supersedes_revision_id).first()
        if prior and prior.status == "PUBLISHED":
            prior.status = "SUPERSEDED"

    log_change(db, "workflow_revision", obj.id, "status", "DRAFT", "PUBLISHED", user.email)
    db.commit()
    db.refresh(obj)
    return obj


@router.post("/{workflow_id}/revisions/{revision_id}/clone", response_model=schemas.WorkflowRevisionOut)
def clone_revision(
    slug: str,
    workflow_id: int,
    revision_id: int,
    payload: schemas.WorkflowRevisionCloneRequest,
    db: Session = Depends(get_project_db),
    user: models.User = Depends(require_tester),
):
    """Corrections to a published workflow revision never edit it in
    place -- clones its steps and links into a brand new DRAFT."""
    original = _get_revision(db, workflow_id, revision_id)
    existing_label = (
        db.query(models.WorkflowRevision)
        .filter(models.WorkflowRevision.workflow_id == workflow_id, models.WorkflowRevision.revision_label == payload.revision_label)
        .first()
    )
    if existing_label:
        raise HTTPException(status_code=400, detail="A revision with that label already exists for this workflow")

    max_sort = (
        db.query(models.WorkflowRevision.revision_number_sort)
        .filter(models.WorkflowRevision.workflow_id == workflow_id)
        .order_by(models.WorkflowRevision.revision_number_sort.desc())
        .first()
    )
    next_sort = (max_sort[0] + 1) if max_sort else 1

    clone = models.WorkflowRevision(
        workflow_id=workflow_id,
        revision_label=payload.revision_label,
        revision_number_sort=next_sort,
        status="DRAFT",
        change_summary=payload.change_summary,
        created_by=user.email,
        supersedes_revision_id=original.id,
    )
    db.add(clone)
    db.flush()

    original_steps = (
        db.query(models.WorkflowStep)
        .filter(models.WorkflowStep.revision_id == original.id)
        .order_by(models.WorkflowStep.sequence_no)
        .all()
    )
    for step in original_steps:
        data = {
            c.name: getattr(step, c.name)
            for c in models.WorkflowStep.__table__.columns
            if c.name not in ("id", "revision_id", "created_at")
        }
        db.add(models.WorkflowStep(revision_id=clone.id, **data))

    original_links = db.query(models.WorkflowTestCaseLink).filter(models.WorkflowTestCaseLink.workflow_revision_id == original.id).all()
    for link in original_links:
        db.add(
            models.WorkflowTestCaseLink(
                workflow_revision_id=clone.id,
                test_case_id=link.test_case_id,
                logical_case_key=link.logical_case_key,
                created_by=user.email,
            )
        )

    db.commit()
    db.refresh(clone)
    return clone


# ---------- Workflow steps ----------


@router.get("/{workflow_id}/revisions/{revision_id}/steps", response_model=list[schemas.WorkflowStepOut])
def list_steps(slug: str, workflow_id: int, revision_id: int, db: Session = Depends(get_project_db)):
    _get_revision(db, workflow_id, revision_id)
    return (
        db.query(models.WorkflowStep)
        .filter(models.WorkflowStep.revision_id == revision_id)
        .order_by(models.WorkflowStep.sequence_no)
        .all()
    )


@router.post("/{workflow_id}/revisions/{revision_id}/steps", response_model=schemas.WorkflowStepOut)
def create_step(
    slug: str,
    workflow_id: int,
    revision_id: int,
    payload: schemas.WorkflowStepCreate,
    db: Session = Depends(get_project_db),
    user: models.User = Depends(require_tester),
):
    revision = _get_revision(db, workflow_id, revision_id)
    _require_draft(revision)
    data = payload.model_dump()
    _validate_step_fields(data["step_type"], data)

    max_seq = (
        db.query(models.WorkflowStep.sequence_no)
        .filter(models.WorkflowStep.revision_id == revision_id)
        .order_by(models.WorkflowStep.sequence_no.desc())
        .first()
    )
    next_seq = (max_seq[0] + 1) if max_seq else 1
    obj = models.WorkflowStep(revision_id=revision_id, sequence_no=next_seq, **data)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.put("/{workflow_id}/revisions/{revision_id}/steps/{step_id}", response_model=schemas.WorkflowStepOut)
def update_step(
    slug: str,
    workflow_id: int,
    revision_id: int,
    step_id: int,
    payload: schemas.WorkflowStepUpdate,
    db: Session = Depends(get_project_db),
    user: models.User = Depends(require_tester),
):
    revision = _get_revision(db, workflow_id, revision_id)
    _require_draft(revision)
    obj = db.query(models.WorkflowStep).filter(models.WorkflowStep.id == step_id, models.WorkflowStep.revision_id == revision_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Workflow step not found")

    updates = payload.model_dump(exclude_unset=True)
    merged = {
        "step_type": updates.get("step_type", obj.step_type),
        "locator_strategy": updates.get("locator_strategy", obj.locator_strategy),
        "locator_value": updates.get("locator_value", obj.locator_value),
        "input_value": updates.get("input_value", obj.input_value),
        "expected_value": updates.get("expected_value", obj.expected_value),
        "checkpoint_instructions": updates.get("checkpoint_instructions", obj.checkpoint_instructions),
        "is_sensitive": updates.get("is_sensitive", obj.is_sensitive),
        "evidence_policy": updates.get("evidence_policy", obj.evidence_policy),
        "repeat_count": updates.get("repeat_count", obj.repeat_count),
    }
    _validate_step_fields(merged["step_type"], merged)

    diffs = {k: (getattr(obj, k), v) for k, v in updates.items() if getattr(obj, k) != v}
    for key, value in updates.items():
        setattr(obj, key, value)
    log_changes(db, "workflow_step", step_id, diffs, user.email)
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/{workflow_id}/revisions/{revision_id}/steps/{step_id}")
def delete_step(
    slug: str,
    workflow_id: int,
    revision_id: int,
    step_id: int,
    db: Session = Depends(get_project_db),
    _user: models.User = Depends(require_tester),
):
    revision = _get_revision(db, workflow_id, revision_id)
    _require_draft(revision)
    obj = db.query(models.WorkflowStep).filter(models.WorkflowStep.id == step_id, models.WorkflowStep.revision_id == revision_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Workflow step not found")
    db.delete(obj)
    db.commit()
    return {"ok": True}


@router.post("/{workflow_id}/revisions/{revision_id}/steps/reorder", response_model=list[schemas.WorkflowStepOut])
def reorder_steps(
    slug: str,
    workflow_id: int,
    revision_id: int,
    payload: schemas.WorkflowStepReorderRequest,
    db: Session = Depends(get_project_db),
    user: models.User = Depends(require_tester),
):
    revision = _get_revision(db, workflow_id, revision_id)
    _require_draft(revision)
    steps = {s.id: s for s in db.query(models.WorkflowStep).filter(models.WorkflowStep.revision_id == revision_id).all()}
    if set(payload.step_ids_in_order) != set(steps.keys()):
        raise HTTPException(status_code=400, detail="step_ids_in_order must contain exactly this revision's current step ids")

    for i, step_id in enumerate(payload.step_ids_in_order, start=1):
        steps[step_id].sequence_no = i
    db.commit()
    return (
        db.query(models.WorkflowStep)
        .filter(models.WorkflowStep.revision_id == revision_id)
        .order_by(models.WorkflowStep.sequence_no)
        .all()
    )


# ---------- Workflow <-> test case links ----------


@router.get("/{workflow_id}/revisions/{revision_id}/links", response_model=list[schemas.WorkflowTestCaseLinkOut])
def list_links(slug: str, workflow_id: int, revision_id: int, db: Session = Depends(get_project_db)):
    _get_revision(db, workflow_id, revision_id)
    links = db.query(models.WorkflowTestCaseLink).filter(models.WorkflowTestCaseLink.workflow_revision_id == revision_id).all()
    case_by_id = {
        c.id: c for c in db.query(models.TestCase).filter(models.TestCase.id.in_([link.test_case_id for link in links])).all()
    }
    out = []
    for link in links:
        item = schemas.WorkflowTestCaseLinkOut.model_validate(link)
        case = case_by_id.get(link.test_case_id)
        if case:
            item.checkpoint_code = case.checkpoint_code
            item.case_title = case.title
        out.append(item)
    return out


@router.post("/{workflow_id}/revisions/{revision_id}/links", response_model=schemas.WorkflowTestCaseLinkOut)
def create_link(
    slug: str,
    workflow_id: int,
    revision_id: int,
    payload: schemas.WorkflowTestCaseLinkCreate,
    db: Session = Depends(get_project_db),
    user: models.User = Depends(require_tester),
):
    revision = _get_revision(db, workflow_id, revision_id)
    _require_draft(revision)
    case = db.query(models.TestCase).filter(models.TestCase.id == payload.test_case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Test case not found")
    existing = (
        db.query(models.WorkflowTestCaseLink)
        .filter(
            models.WorkflowTestCaseLink.workflow_revision_id == revision_id,
            models.WorkflowTestCaseLink.test_case_id == payload.test_case_id,
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="This test case is already linked to this workflow revision")

    obj = models.WorkflowTestCaseLink(
        workflow_revision_id=revision_id,
        test_case_id=case.id,
        logical_case_key=case.logical_case_key or case.checkpoint_code,
        created_by=user.email,
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    out = schemas.WorkflowTestCaseLinkOut.model_validate(obj)
    out.checkpoint_code = case.checkpoint_code
    out.case_title = case.title
    return out


@router.delete("/{workflow_id}/revisions/{revision_id}/links/{link_id}")
def delete_link(
    slug: str,
    workflow_id: int,
    revision_id: int,
    link_id: int,
    db: Session = Depends(get_project_db),
    _user: models.User = Depends(require_tester),
):
    revision = _get_revision(db, workflow_id, revision_id)
    _require_draft(revision)
    obj = (
        db.query(models.WorkflowTestCaseLink)
        .filter(models.WorkflowTestCaseLink.id == link_id, models.WorkflowTestCaseLink.workflow_revision_id == revision_id)
        .first()
    )
    if not obj:
        raise HTTPException(status_code=404, detail="Link not found")
    db.delete(obj)
    db.commit()
    return {"ok": True}
