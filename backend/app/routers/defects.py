from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_project_db
from ..auth import get_current_user, require_tester

router = APIRouter(prefix="/api/{slug}/defects", tags=["defects"], dependencies=[Depends(get_current_user)])


@router.get("", response_model=list[schemas.DefectOut])
def list_defects(
    slug: str,
    cycle_id: int | None = None,
    status: str | None = None,
    severity: str | None = None,
    db: Session = Depends(get_project_db),
):
    q = db.query(models.Defect)
    if cycle_id is not None:
        q = q.filter(models.Defect.cycle_id == cycle_id)
    if status:
        q = q.filter(models.Defect.status == status)
    if severity:
        q = q.filter(models.Defect.severity == severity)
    return q.order_by(models.Defect.created_at.desc()).all()


@router.post("", response_model=schemas.DefectOut)
def create_defect(
    slug: str,
    payload: schemas.DefectCreate,
    db: Session = Depends(get_project_db),
    user: models.User = Depends(require_tester),
):
    if payload.severity not in models.DEFECT_SEVERITIES:
        raise HTTPException(status_code=400, detail=f"severity must be one of {models.DEFECT_SEVERITIES}")
    max_id = db.query(models.Defect.id).order_by(models.Defect.id.desc()).first()
    next_seq = (max_id[0] + 1) if max_id else 1
    defect = models.Defect(
        cycle_id=payload.cycle_id,
        cycle_test_result_id=payload.cycle_test_result_id,
        defect_key=f"DEF-{next_seq}",
        title=payload.title,
        description_md=payload.description_md,
        severity=payload.severity,
        external_url=payload.external_url,
        created_by=user.email,
        workflow_run_id=payload.workflow_run_id,
        workflow_step_run_id=payload.workflow_step_run_id,
        checkpoint_decision_id=payload.checkpoint_decision_id,
    )
    db.add(defect)
    db.commit()
    db.refresh(defect)
    return defect


@router.put("/{defect_id}", response_model=schemas.DefectOut)
def update_defect(
    slug: str,
    defect_id: int,
    payload: schemas.DefectUpdate,
    db: Session = Depends(get_project_db),
    _user: models.User = Depends(require_tester),
):
    defect = db.query(models.Defect).filter(models.Defect.id == defect_id).first()
    if not defect:
        raise HTTPException(status_code=404, detail="Defect not found")
    updates = payload.model_dump(exclude_unset=True)
    if "severity" in updates and updates["severity"] not in models.DEFECT_SEVERITIES:
        raise HTTPException(status_code=400, detail=f"severity must be one of {models.DEFECT_SEVERITIES}")
    if "status" in updates and updates["status"] not in models.DEFECT_STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {models.DEFECT_STATUSES}")
    for key, value in updates.items():
        setattr(defect, key, value)
    db.commit()
    db.refresh(defect)
    return defect
