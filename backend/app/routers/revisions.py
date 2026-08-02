from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_project_db
from ..auth import get_current_user, require_tester, require_admin
from .cycles import create_cycle_with_snapshot, most_recently_used_environment, _to_out as _cycle_to_out

router = APIRouter(
    prefix="/api/{slug}/suites/{suite_id}/revisions", tags=["revisions"], dependencies=[Depends(get_current_user)]
)


def _get_suite(db: Session, suite_id: int) -> models.TestSuite:
    suite = db.query(models.TestSuite).filter(models.TestSuite.id == suite_id).first()
    if not suite:
        raise HTTPException(status_code=404, detail="Suite not found")
    return suite


@router.get("", response_model=list[schemas.RevisionOut])
def list_revisions(slug: str, suite_id: int, db: Session = Depends(get_project_db)):
    _get_suite(db, suite_id)
    return (
        db.query(models.ScriptRevision)
        .filter(models.ScriptRevision.suite_id == suite_id)
        .order_by(models.ScriptRevision.revision_number_sort.desc())
        .all()
    )


@router.post("", response_model=schemas.RevisionOut)
def create_revision(
    slug: str,
    suite_id: int,
    payload: schemas.RevisionCreate,
    db: Session = Depends(get_project_db),
    user: models.User = Depends(require_tester),
):
    _get_suite(db, suite_id)
    existing = (
        db.query(models.ScriptRevision)
        .filter(models.ScriptRevision.suite_id == suite_id, models.ScriptRevision.revision_label == payload.revision_label)
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="A revision with that label already exists in this suite")
    max_sort = (
        db.query(models.ScriptRevision.revision_number_sort)
        .filter(models.ScriptRevision.suite_id == suite_id)
        .order_by(models.ScriptRevision.revision_number_sort.desc())
        .first()
    )
    next_sort = (max_sort[0] + 1) if max_sort else 1
    obj = models.ScriptRevision(
        suite_id=suite_id,
        revision_label=payload.revision_label,
        revision_number_sort=next_sort,
        status="DRAFT",
        change_summary=payload.change_summary,
        source_type="MANUAL",
        imported_at=datetime.utcnow(),
        imported_by=user.email,
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("/{revision_id}", response_model=schemas.RevisionOut)
def get_revision(slug: str, suite_id: int, revision_id: int, db: Session = Depends(get_project_db)):
    obj = (
        db.query(models.ScriptRevision)
        .filter(models.ScriptRevision.id == revision_id, models.ScriptRevision.suite_id == suite_id)
        .first()
    )
    if not obj:
        raise HTTPException(status_code=404, detail="Revision not found")
    return obj


# Publishing is deliberately restricted to ADMIN, not the broader TESTER
# role — the import workflow (rebuild prompt section 11) requires "Admin
# review" between an unreviewed import/draft and an immutable publish.
@router.post("/{revision_id}/publish", response_model=schemas.RevisionOut)
def publish_revision(
    slug: str,
    suite_id: int,
    revision_id: int,
    db: Session = Depends(get_project_db),
    user: models.User = Depends(require_admin),
):
    obj = (
        db.query(models.ScriptRevision)
        .filter(models.ScriptRevision.id == revision_id, models.ScriptRevision.suite_id == suite_id)
        .first()
    )
    if not obj:
        raise HTTPException(status_code=404, detail="Revision not found")
    if obj.status != "DRAFT":
        raise HTTPException(status_code=400, detail=f"Only a DRAFT revision can be published (current status: {obj.status})")
    has_cases = db.query(models.TestCase).filter(models.TestCase.revision_id == revision_id).first()
    if not has_cases:
        raise HTTPException(status_code=400, detail="Cannot publish a revision with no test cases")

    obj.status = "PUBLISHED"
    obj.published_at = datetime.utcnow()
    obj.published_by = user.email

    # A correction-clone records which revision it supersedes — publishing
    # it retires that prior revision so a suite has at most one currently
    # PUBLISHED revision at a time (existing test cycles keep pointing at
    # whichever revision they were created against; see script_revisions'
    # immutability rule — this never rewrites an existing cycle).
    if obj.supersedes_revision_id:
        prior = db.query(models.ScriptRevision).filter(models.ScriptRevision.id == obj.supersedes_revision_id).first()
        if prior and prior.status == "PUBLISHED":
            prior.status = "SUPERSEDED"

    db.commit()
    db.refresh(obj)
    return obj


@router.post("/{revision_id}/clone", response_model=schemas.RevisionOut)
def clone_revision(
    slug: str,
    suite_id: int,
    revision_id: int,
    payload: schemas.RevisionCloneRequest,
    db: Session = Depends(get_project_db),
    user: models.User = Depends(require_tester),
):
    """Corrections to a published revision never edit it in place — this
    clones its current case set into a brand new DRAFT revision."""
    original = (
        db.query(models.ScriptRevision)
        .filter(models.ScriptRevision.id == revision_id, models.ScriptRevision.suite_id == suite_id)
        .first()
    )
    if not original:
        raise HTTPException(status_code=404, detail="Revision not found")
    existing_label = (
        db.query(models.ScriptRevision)
        .filter(models.ScriptRevision.suite_id == suite_id, models.ScriptRevision.revision_label == payload.revision_label)
        .first()
    )
    if existing_label:
        raise HTTPException(status_code=400, detail="A revision with that label already exists in this suite")

    max_sort = (
        db.query(models.ScriptRevision.revision_number_sort)
        .filter(models.ScriptRevision.suite_id == suite_id)
        .order_by(models.ScriptRevision.revision_number_sort.desc())
        .first()
    )
    next_sort = (max_sort[0] + 1) if max_sort else 1

    clone = models.ScriptRevision(
        suite_id=suite_id,
        revision_label=payload.revision_label,
        revision_number_sort=next_sort,
        status="DRAFT",
        change_summary=payload.change_summary,
        source_type="CLONE",
        imported_at=datetime.utcnow(),
        imported_by=payload.created_by or user.email,
        supersedes_revision_id=original.id,
    )
    db.add(clone)
    db.flush()  # assigns clone.id before copying cases

    original_cases = db.query(models.TestCase).filter(models.TestCase.revision_id == original.id).all()
    for case in original_cases:
        data = {
            c.name: getattr(case, c.name)
            for c in models.TestCase.__table__.columns
            if c.name not in ("id", "revision_id", "created_at")
        }
        db.add(models.TestCase(revision_id=clone.id, **data))

    db.commit()
    db.refresh(clone)
    return clone


@router.post("/{revision_id}/run-now", response_model=schemas.TestCycleOut)
def run_now(
    slug: str,
    suite_id: int,
    revision_id: int,
    payload: schemas.RunNowRequest,
    db: Session = Depends(get_project_db),
    user: models.User = Depends(require_tester),
):
    """One click, from a published suite revision straight to an active
    cycle — no separate navigation to Test Cycles required. Generates a
    sensible cycle name (suite + timestamp) and defaults to the most
    recently used environment project-wide."""
    suite = _get_suite(db, suite_id)
    revision = (
        db.query(models.ScriptRevision)
        .filter(models.ScriptRevision.id == revision_id, models.ScriptRevision.suite_id == suite_id)
        .first()
    )
    if not revision:
        raise HTTPException(status_code=404, detail="Revision not found")
    if revision.status != "PUBLISHED":
        raise HTTPException(status_code=400, detail=f"Run Now requires a PUBLISHED revision (current status: {revision.status})")

    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    environment = payload.environment or most_recently_used_environment(db)
    cycle = create_cycle_with_snapshot(
        db, user.email,
        suite_id=suite_id, script_revision_id=revision_id,
        name=f"{suite.name} — {timestamp}",
        environment=environment,
        require_evidence_for_pass=payload.require_evidence_for_pass,
    )
    db.commit()
    db.refresh(cycle)
    return _cycle_to_out(db, cycle)
