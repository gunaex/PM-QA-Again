from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_master_db
from ..auth import issue_runner_token, revoke_runner_token, require_admin, get_current_user

router = APIRouter(prefix="/api/runner-tokens", tags=["runner-tokens"])

# HYB-2: a runner counts ONLINE if it's called the API (any call touches
# last_heartbeat_at — see auth.py::get_current_runner) within this
# window; STALE if it has a heartbeat but it's older than that; OFFLINE
# if it has never made an authenticated call yet.
ONLINE_WINDOW_SECONDS = 90


def _status_for(record: models.RunnerToken) -> str:
    if record.revoked:
        return "REVOKED"
    if not record.last_heartbeat_at:
        return "OFFLINE"
    age = datetime.utcnow() - record.last_heartbeat_at
    return "ONLINE" if age <= timedelta(seconds=ONLINE_WINDOW_SECONDS) else "STALE"


def _to_out(record: models.RunnerToken) -> schemas.RunnerRegistrationOut:
    out = schemas.RunnerRegistrationOut.model_validate(record)
    out.status = _status_for(record)
    return out


@router.post("", response_model=schemas.RunnerTokenOut)
def create_runner_token(
    payload: schemas.RunnerTokenCreate,
    db: Session = Depends(get_master_db),
    _admin: models.User = Depends(require_admin),
):
    """Mints a runner token and returns the raw value once — it is never
    retrievable again (only its hash is stored, same discipline as
    refresh tokens)."""
    raw_token, record = issue_runner_token(db, payload.label)
    return schemas.RunnerTokenOut(id=record.id, label=record.label, token=raw_token)


@router.get("", response_model=list[schemas.RunnerRegistrationOut])
def list_runner_tokens(db: Session = Depends(get_master_db), _admin: models.User = Depends(require_admin)):
    records = db.query(models.RunnerToken).order_by(models.RunnerToken.created_at.desc()).all()
    return [_to_out(r) for r in records]


@router.get("/status", response_model=schemas.RunnerFleetStatusOut)
def runner_fleet_status(db: Session = Depends(get_master_db), _user: models.User = Depends(get_current_user)):
    """Deliberately not require_admin: any authenticated user (including
    TESTER, queuing their own run) needs to know whether a QUEUED run
    will ever actually get picked up -- without this, "nothing happens
    after Queue Run" looks indistinguishable from broken. Returns only
    an aggregate boolean, never labels/ids/tokens -- the detailed
    per-runner list (list_runner_tokens above) stays ADMIN-only."""
    records = db.query(models.RunnerToken).filter(models.RunnerToken.revoked == False).all()  # noqa: E712
    any_online = any(_status_for(r) == "ONLINE" for r in records)
    return schemas.RunnerFleetStatusOut(any_online=any_online)


@router.put("/{token_id}/revoke", response_model=schemas.RunnerRegistrationOut)
def revoke_token(token_id: int, db: Session = Depends(get_master_db), _admin: models.User = Depends(require_admin)):
    record = revoke_runner_token(db, token_id)
    return _to_out(record)
