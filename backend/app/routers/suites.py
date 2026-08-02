from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_project_db
from ..activity import log_changes
from ..auth import require_tester, require_project_access

router = APIRouter(prefix="/api/{slug}/suites", tags=["suites"], dependencies=[Depends(require_project_access)])


@router.get("", response_model=list[schemas.TestSuiteOut])
def list_suites(slug: str, include_system_generated: bool = False, db: Session = Depends(get_project_db)):
    """Quick Manual Test entry flow: the shared, auto-created "Quick
    Tests" suite is hidden here by default (still a fully real,
    auditable, exportable TestSuite row) -- pass
    include_system_generated=true to show it, matching the existing
    "Show archived" toggle pattern elsewhere in this app."""
    q = db.query(models.TestSuite)
    if not include_system_generated:
        q = q.filter(models.TestSuite.is_system_generated.is_(False))
    return q.order_by(models.TestSuite.created_at.desc()).all()


@router.post("", response_model=schemas.TestSuiteOut)
def create_suite(
    slug: str,
    payload: schemas.TestSuiteCreate,
    db: Session = Depends(get_project_db),
    user: models.User = Depends(require_tester),
):
    if payload.suite_type not in models.SUITE_TYPES:
        raise HTTPException(status_code=400, detail=f"suite_type must be one of {models.SUITE_TYPES}")
    obj = models.TestSuite(**payload.model_dump(), created_by=user.email)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("/{suite_id}", response_model=schemas.TestSuiteOut)
def get_suite(slug: str, suite_id: int, db: Session = Depends(get_project_db)):
    obj = db.query(models.TestSuite).filter(models.TestSuite.id == suite_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Suite not found")
    return obj


@router.put("/{suite_id}", response_model=schemas.TestSuiteOut)
def update_suite(
    slug: str,
    suite_id: int,
    payload: schemas.TestSuiteUpdate,
    db: Session = Depends(get_project_db),
    user: models.User = Depends(require_tester),
):
    obj = db.query(models.TestSuite).filter(models.TestSuite.id == suite_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Suite not found")
    updates = payload.model_dump(exclude_unset=True)
    if "suite_type" in updates and updates["suite_type"] not in models.SUITE_TYPES:
        raise HTTPException(status_code=400, detail=f"suite_type must be one of {models.SUITE_TYPES}")
    diffs = {k: (getattr(obj, k), v) for k, v in updates.items() if getattr(obj, k) != v}
    for key, value in updates.items():
        setattr(obj, key, value)
    log_changes(db, "suite", suite_id, diffs, user.email)
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/{suite_id}")
def delete_suite(
    slug: str,
    suite_id: int,
    db: Session = Depends(get_project_db),
    _user: models.User = Depends(require_tester),
):
    obj = db.query(models.TestSuite).filter(models.TestSuite.id == suite_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Suite not found")
    has_revisions = db.query(models.ScriptRevision).filter(models.ScriptRevision.suite_id == suite_id).first()
    if has_revisions:
        raise HTTPException(status_code=400, detail="Cannot delete a suite that has script revisions")
    db.delete(obj)
    db.commit()
    return {"ok": True}
