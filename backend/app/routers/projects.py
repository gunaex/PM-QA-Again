import json
import os
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import (
    get_master_db,
    get_project_engine,
    get_project_db,
    project_db_exists,
    project_db_path,
    dispose_project_engine,
)
from ..auth import get_current_user, require_admin, require_project_access, verify_password
from ..quota import quota_status

router = APIRouter(prefix="/api/projects", tags=["projects"], dependencies=[Depends(get_current_user)])

# A project slug matching one of these would permanently collide with a
# fixed-literal-prefix router — reserved so slugify() always routes around
# them instead (mirrors PM-Again's RESERVED_SLUGS reasoning).
RESERVED_SLUGS = {"auth", "projects", "health"}


def slugify(name: str) -> str:
    slug = name.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug or "project"


@router.post("", response_model=schemas.ProjectOut)
def create_project(
    payload: schemas.ProjectCreate,
    db: Session = Depends(get_master_db),
    # ADR-0003: only ADMIN creates a project -- TESTER/VIEWER access is
    # always explicitly assigned afterward via project-membership, never
    # implicit from having created it.
    _user: models.User = Depends(require_admin),
):
    base_slug = slugify(payload.name)
    slug = base_slug
    suffix = 1
    while slug in RESERVED_SLUGS or db.query(models.Project).filter(models.Project.slug == slug).first():
        suffix += 1
        slug = f"{base_slug}-{suffix}"

    project = models.Project(
        name=payload.name,
        slug=slug,
        external_project_url=payload.external_project_url,
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    # Provision an empty per-project SQLite DB with all tables created.
    get_project_engine(slug)

    return project


@router.get("", response_model=list[schemas.ProjectOut])
def list_projects(
    include_archived: bool = Query(False),
    db: Session = Depends(get_master_db),
    user: models.User = Depends(get_current_user),
):
    q = db.query(models.Project)
    if not include_archived:
        q = q.filter(models.Project.archived == False)  # noqa: E712
    # ADR-0003: ADMIN sees every project; TESTER/VIEWER only see projects
    # they have an explicit ProjectMembership row for.
    if user.role != "ADMIN":
        member_project_ids = db.query(models.ProjectMembership.project_id).filter(models.ProjectMembership.user_id == user.id)
        q = q.filter(models.Project.id.in_(member_project_ids))
    return q.order_by(models.Project.created_at.desc()).all()


@router.get("/{slug}", response_model=schemas.ProjectOut)
def get_project(slug: str, db: Session = Depends(get_master_db), _access: models.User = Depends(require_project_access)):
    project = db.query(models.Project).filter(models.Project.slug == slug).first()
    if not project_db_exists(slug):
        get_project_engine(slug)
    return project


# Archive/delete are the most consequential actions in the app (hiding or
# permanently destroying a whole project's data) — restricted to ADMIN
# specifically, and both require the requesting user to re-enter their own
# current password, same check as changing your password, as a deliberate
# extra confirmation step before something this hard to reverse.
@router.put("/{slug}/archive", response_model=schemas.ProjectOut)
def archive_project(
    slug: str,
    payload: schemas.ProjectArchiveRequest,
    db: Session = Depends(get_master_db),
    user: models.User = Depends(require_admin),
):
    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    project = db.query(models.Project).filter(models.Project.slug == slug).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    project.archived = payload.archived
    db.commit()
    db.refresh(project)
    return project


@router.delete("/{slug}")
def delete_project(
    slug: str,
    payload: schemas.ProjectDeleteRequest,
    db: Session = Depends(get_master_db),
    user: models.User = Depends(require_admin),
):
    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    project = db.query(models.Project).filter(models.Project.slug == slug).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    db.delete(project)
    db.commit()

    dispose_project_engine(slug)
    db_path = project_db_path(slug)
    if os.path.exists(db_path):
        os.remove(db_path)

    return {"ok": True}


# ---------- Evidence storage quota (ADR-0002, requirement 9) ----------


@router.get("/{slug}/storage-quota", response_model=schemas.StorageQuotaOut)
def get_storage_quota(
    slug: str,
    master_db: Session = Depends(get_master_db),
    project_db: Session = Depends(get_project_db),
    _access: models.User = Depends(require_project_access),
):
    project = master_db.query(models.Project).filter(models.Project.slug == slug).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return quota_status(project, project_db)


@router.put("/{slug}/storage-quota", response_model=schemas.StorageQuotaOut)
def update_storage_quota(
    slug: str,
    payload: schemas.StorageQuotaUpdate,
    master_db: Session = Depends(get_master_db),
    project_db: Session = Depends(get_project_db),
    _admin: models.User = Depends(require_admin),
):
    project = master_db.query(models.Project).filter(models.Project.slug == slug).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if payload.storage_quota_bytes is not None:
        if payload.storage_quota_bytes <= 0:
            raise HTTPException(status_code=400, detail="storage_quota_bytes must be positive")
        project.storage_quota_bytes = payload.storage_quota_bytes
    if payload.storage_warning_thresholds is not None:
        if not all(0 < t <= 100 for t in payload.storage_warning_thresholds):
            raise HTTPException(status_code=400, detail="storage_warning_thresholds must all be between 1 and 100")
        project.storage_warning_thresholds = json.dumps(sorted(payload.storage_warning_thresholds))
    master_db.commit()
    master_db.refresh(project)
    return quota_status(project, project_db)
