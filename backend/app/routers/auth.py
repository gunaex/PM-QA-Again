from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_master_db
from ..auth import (
    hash_password,
    verify_password,
    create_access_token,
    issue_refresh_token,
    consume_refresh_token,
    revoke_refresh_token,
    set_auth_cookies,
    clear_auth_cookies,
    get_current_user,
    require_admin,
)
from ..rate_limit import limiter

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=schemas.UserOut)
@limiter.limit("5/minute")
def login(request: Request, response: Response, payload: schemas.LoginRequest, db: Session = Depends(get_master_db)):
    user = db.query(models.User).filter(models.User.email == payload.email).first()
    # Same error for "no such user" and "wrong password" — don't leak which
    # one it was (avoids account enumeration).
    if not user or not user.active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    access_token = create_access_token(user)
    refresh_token = issue_refresh_token(db, user)
    set_auth_cookies(response, access_token, refresh_token)
    return user


@router.post("/refresh")
def refresh(request: Request, response: Response, db: Session = Depends(get_master_db)):
    raw_refresh = request.cookies.get("refresh_token")
    if not raw_refresh:
        raise HTTPException(status_code=401, detail="No refresh token")

    record = consume_refresh_token(db, raw_refresh)
    user = db.query(models.User).filter(models.User.id == record.user_id).first()
    if not user or not user.active:
        raise HTTPException(status_code=401, detail="User not found or inactive")

    access_token = create_access_token(user)
    new_refresh_token = issue_refresh_token(db, user)
    set_auth_cookies(response, access_token, new_refresh_token)
    return {"ok": True}


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_master_db)):
    raw_refresh = request.cookies.get("refresh_token")
    if raw_refresh:
        revoke_refresh_token(db, raw_refresh)
    clear_auth_cookies(response)
    return {"ok": True}


@router.get("/me", response_model=schemas.UserOut)
def me(user: models.User = Depends(get_current_user)):
    return user


@router.post("/change-password", response_model=schemas.UserOut)
def change_password(
    payload: schemas.ChangePasswordRequest,
    db: Session = Depends(get_master_db),
    user: models.User = Depends(get_current_user),
):
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    user.password_hash = hash_password(payload.new_password)
    user.must_change_password = False
    db.commit()
    db.refresh(user)
    return user


# ---------- User management (ADMIN only) ----------
# Without this, only the bootstrap admin account could ever exist.


@router.post("/users", response_model=schemas.UserOut)
def create_user(
    payload: schemas.UserCreate,
    db: Session = Depends(get_master_db),
    _admin: models.User = Depends(require_admin),
):
    if db.query(models.User).filter(models.User.email == payload.email).first():
        raise HTTPException(status_code=400, detail="A user with that email already exists")
    if payload.role not in models.ROLES:
        raise HTTPException(status_code=400, detail=f"role must be one of {models.ROLES}")
    # New accounts are handed a password by an admin, not chosen by the
    # account holder — force a change on first login, same as the bootstrap
    # admin account.
    user = models.User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        role=payload.role,
        must_change_password=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.get("/users", response_model=list[schemas.UserOut])
def list_users(db: Session = Depends(get_master_db), _admin: models.User = Depends(require_admin)):
    return db.query(models.User).order_by(models.User.id).all()


@router.put("/users/{user_id}", response_model=schemas.UserOut)
def set_user_active(
    user_id: int,
    payload: schemas.UserActiveUpdate,
    db: Session = Depends(get_master_db),
    _admin: models.User = Depends(require_admin),
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.active = payload.active
    db.commit()
    db.refresh(user)
    return user


# ---------- Project membership (ADR-0003) ----------
# Which projects a TESTER/VIEWER can reach -- ADMIN always reaches every
# project and never needs a row here (see require_project_access in
# ../auth.py). Same require_admin gating as the user-management endpoints
# above.


@router.get("/users/{user_id}/projects", response_model=list[schemas.ProjectMembershipOut])
def list_user_projects(user_id: int, db: Session = Depends(get_master_db), _admin: models.User = Depends(require_admin)):
    if not db.query(models.User).filter(models.User.id == user_id).first():
        raise HTTPException(status_code=404, detail="User not found")
    rows = (
        db.query(models.ProjectMembership, models.Project)
        .join(models.Project, models.Project.id == models.ProjectMembership.project_id)
        .filter(models.ProjectMembership.user_id == user_id)
        .order_by(models.Project.name)
        .all()
    )
    return [
        schemas.ProjectMembershipOut(project_id=project.id, project_name=project.name, project_slug=project.slug)
        for _membership, project in rows
    ]


@router.post("/users/{user_id}/projects", response_model=schemas.ProjectMembershipOut)
def add_user_project(
    user_id: int,
    payload: schemas.ProjectMembershipCreate,
    db: Session = Depends(get_master_db),
    _admin: models.User = Depends(require_admin),
):
    if not db.query(models.User).filter(models.User.id == user_id).first():
        raise HTTPException(status_code=404, detail="User not found")
    project = db.query(models.Project).filter(models.Project.id == payload.project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    existing = (
        db.query(models.ProjectMembership)
        .filter(models.ProjectMembership.user_id == user_id, models.ProjectMembership.project_id == project.id)
        .first()
    )
    if not existing:
        db.add(models.ProjectMembership(user_id=user_id, project_id=project.id))
        db.commit()
    return schemas.ProjectMembershipOut(project_id=project.id, project_name=project.name, project_slug=project.slug)


@router.delete("/users/{user_id}/projects/{project_id}")
def remove_user_project(
    user_id: int,
    project_id: int,
    db: Session = Depends(get_master_db),
    _admin: models.User = Depends(require_admin),
):
    db.query(models.ProjectMembership).filter(
        models.ProjectMembership.user_id == user_id, models.ProjectMembership.project_id == project_id
    ).delete()
    db.commit()
    return {"ok": True}
