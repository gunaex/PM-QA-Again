from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from .. import models
from ..database import get_project_db, get_master_db
from ..auth import get_current_user, require_project_access
from ..storage import EvidenceStorage, get_evidence_storage
from ..report_excel import build_workbook, workbook_to_bytes
from ..report_zip import build_evidence_package

router = APIRouter(prefix="/api/{slug}/cycles/{cycle_id}/export", tags=["export"], dependencies=[Depends(require_project_access)])


def _get_project_and_cycle(slug: str, cycle_id: int, db: Session, master_db: Session):
    project = master_db.query(models.Project).filter(models.Project.slug == slug).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    cycle = db.query(models.TestCycle).filter(models.TestCycle.id == cycle_id).first()
    if not cycle:
        raise HTTPException(status_code=404, detail="Cycle not found")
    return project, cycle


@router.get("/excel")
def export_excel(
    slug: str,
    cycle_id: int,
    db: Session = Depends(get_project_db),
    master_db: Session = Depends(get_master_db),
    user: models.User = Depends(get_current_user),
):
    project, cycle = _get_project_and_cycle(slug, cycle_id, db, master_db)
    wb = build_workbook(db, project, cycle, generated_by=user.email)
    content = workbook_to_bytes(wb)
    filename = f"{slug}_{cycle.name}.xlsx".replace(" ", "_")
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/zip")
def export_zip(
    slug: str,
    cycle_id: int,
    db: Session = Depends(get_project_db),
    master_db: Session = Depends(get_master_db),
    storage: EvidenceStorage = Depends(get_evidence_storage),
    user: models.User = Depends(get_current_user),
):
    """Reads every evidence file server-side through the authorized
    EvidenceStorage abstraction (requirement 1/2) — never a presigned
    URL substituted into the archive."""
    project, cycle = _get_project_and_cycle(slug, cycle_id, db, master_db)
    content, filename = build_evidence_package(db, project, cycle, storage, generated_by=user.email)
    return Response(
        content=content,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
