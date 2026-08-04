from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_project_db
from ..auth import require_admin, require_project_access

router = APIRouter(prefix="/api/{slug}/cycles/{cycle_id}/signoffs", tags=["signoffs"], dependencies=[Depends(require_project_access)])


@router.get("", response_model=list[schemas.SignOffOut])
def list_signoffs(slug: str, cycle_id: int, db: Session = Depends(get_project_db)):
    return (
        db.query(models.SignOff)
        .filter(models.SignOff.cycle_id == cycle_id)
        .order_by(models.SignOff.acted_at.desc())
        .all()
    )


@router.post("", response_model=schemas.SignOffOut)
def create_signoff(
    slug: str,
    cycle_id: int,
    payload: schemas.SignOffCreate,
    db: Session = Depends(get_project_db),
    user: models.User = Depends(require_admin),
):
    """Admin-only — matches the existing N/A-review and cycle-lock/reopen
    pattern for consequential decisions. One row per decision, never
    edited in place."""
    if payload.cycle_id != cycle_id:
        raise HTTPException(status_code=400, detail="cycle_id in path and body must match")
    if payload.signoff_type not in models.SIGNOFF_TYPES:
        raise HTTPException(status_code=400, detail=f"signoff_type must be one of {models.SIGNOFF_TYPES}")
    if payload.decision not in models.SIGNOFF_DECISIONS:
        raise HTTPException(status_code=400, detail=f"decision must be one of {models.SIGNOFF_DECISIONS}")

    signoff = models.SignOff(
        cycle_id=cycle_id,
        signoff_type=payload.signoff_type,
        decision=payload.decision,
        comment_md=payload.comment_md,
        actor=user.email,
    )
    db.add(signoff)
    db.commit()
    db.refresh(signoff)
    return signoff
