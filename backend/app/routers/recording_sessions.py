"""HYB-3: browser workflow recorder session protocol.

Recording happens only inside a Playwright browser the QA Runner itself
launches (never the tester's everyday browser, never a global OS hook).
The claim/lease shape deliberately mirrors workflow_runs.py's job
protocol exactly -- a RecordingSession is claimed outbound-only by a
runner, holds a time-limited lease renewed by heartbeat, and is
lazily marked RUNNER_LOST if the lease expires. The one real
difference: its payload is a buffer of *candidate* RecordedStep rows a
human reviews, edits, and explicitly saves -- never an auto-published
workflow revision.
"""
import json
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_project_db, get_master_db
from ..auth import get_current_user, require_tester, get_current_runner, _hash_token
from .workflows import _validate_step_fields

router = APIRouter(prefix="/api/{slug}/recording-sessions", tags=["recording-sessions"])

LEASE_DURATION_SECONDS = 60


def _require_user_or_runner(request: Request, master_db: Session):
    if request.headers.get("X-Runner-Token"):
        raw_token = request.headers["X-Runner-Token"]
        record = (
            master_db.query(models.RunnerToken)
            .filter(models.RunnerToken.token_hash == _hash_token(raw_token), models.RunnerToken.revoked == False)  # noqa: E712
            .first()
        )
        if not record:
            raise HTTPException(status_code=401, detail="Invalid or revoked runner token")
        record.last_heartbeat_at = datetime.utcnow()
        master_db.commit()
        return
    get_current_user(request=request, db=master_db)


def _expire_stale_leases(db: Session):
    now = datetime.utcnow()
    stale = (
        db.query(models.RecordingSession)
        .filter(
            models.RecordingSession.status.in_(models.RECORDING_SESSION_LEASED_STATUSES),
            models.RecordingSession.lease_expires_at.isnot(None),
            models.RecordingSession.lease_expires_at < now,
        )
        .all()
    )
    for session in stale:
        session.status = "RUNNER_LOST"
    if stale:
        db.commit()


def _get_session(db: Session, session_id: int) -> models.RecordingSession:
    session = db.query(models.RecordingSession).filter(models.RecordingSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Recording session not found")
    return session


def _require_lease(session: models.RecordingSession, runner: models.RunnerToken, lease_token: str):
    if session.runner_id != runner.id or not session.lease_token or session.lease_token != lease_token:
        raise HTTPException(status_code=409, detail="This recording session is not currently leased to you")


def _to_detail(db: Session, session: models.RecordingSession) -> schemas.RecordingSessionDetailOut:
    steps = (
        db.query(models.RecordedStep)
        .filter(models.RecordedStep.recording_session_id == session.id)
        .order_by(models.RecordedStep.sequence_no)
        .all()
    )
    out = schemas.RecordingSessionDetailOut.model_validate(session)
    out.recorded_steps = [schemas.RecordedStepOut.model_validate(s) for s in steps]
    return out


# ---------- human-facing: create / list / control ----------


@router.post("", response_model=schemas.RecordingSessionOut)
def create_session(
    slug: str,
    payload: schemas.RecordingSessionCreate,
    db: Session = Depends(get_project_db),
    user: models.User = Depends(require_tester),
):
    workflow = db.query(models.WorkflowDefinition).filter(models.WorkflowDefinition.id == payload.workflow_id).first()
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    session = models.RecordingSession(
        workflow_id=payload.workflow_id, target_url=payload.target_url, status="REQUESTED", requested_by=user.email,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


@router.get("", response_model=list[schemas.RecordingSessionOut], dependencies=[Depends(get_current_user)])
def list_sessions(slug: str, db: Session = Depends(get_project_db)):
    _expire_stale_leases(db)
    return db.query(models.RecordingSession).order_by(models.RecordingSession.created_at.desc()).all()


@router.get("/{session_id}", response_model=schemas.RecordingSessionDetailOut)
def get_session(slug: str, session_id: int, request: Request, db: Session = Depends(get_project_db), master_db: Session = Depends(get_master_db)):
    _require_user_or_runner(request, master_db)
    _expire_stale_leases(db)
    session = _get_session(db, session_id)
    return _to_detail(db, session)


@router.post("/{session_id}/pause", response_model=schemas.RecordingSessionOut)
def pause_session(slug: str, session_id: int, db: Session = Depends(get_project_db), _user: models.User = Depends(require_tester)):
    session = _get_session(db, session_id)
    if session.status != "RECORDING":
        raise HTTPException(status_code=400, detail=f"Can only pause a RECORDING session (current status: {session.status})")
    session.status = "PAUSED"
    db.commit()
    db.refresh(session)
    return session


@router.post("/{session_id}/resume", response_model=schemas.RecordingSessionOut)
def resume_session(slug: str, session_id: int, db: Session = Depends(get_project_db), _user: models.User = Depends(require_tester)):
    session = _get_session(db, session_id)
    if session.status != "PAUSED":
        raise HTTPException(status_code=400, detail=f"Can only resume a PAUSED session (current status: {session.status})")
    session.status = "RECORDING"
    db.commit()
    db.refresh(session)
    return session


@router.post("/{session_id}/stop", response_model=schemas.RecordingSessionOut)
def stop_session(slug: str, session_id: int, db: Session = Depends(get_project_db), _user: models.User = Depends(require_tester)):
    session = _get_session(db, session_id)
    if session.status not in ("RECORDING", "PAUSED", "CLAIMED"):
        raise HTTPException(status_code=400, detail=f"Cannot stop a session in status {session.status}")
    session.status = "STOPPED"
    db.commit()
    db.refresh(session)
    return session


@router.post("/{session_id}/discard", response_model=schemas.RecordingSessionOut)
def discard_session(slug: str, session_id: int, db: Session = Depends(get_project_db), _user: models.User = Depends(require_tester)):
    session = _get_session(db, session_id)
    if session.status == "SAVED":
        raise HTTPException(status_code=400, detail="Cannot discard a session that was already saved as a draft")
    db.query(models.RecordedStep).filter(models.RecordedStep.recording_session_id == session_id).delete()
    session.status = "DISCARDED"
    db.commit()
    db.refresh(session)
    return session


@router.post("/{session_id}/insert-checkpoint", response_model=schemas.RecordedStepOut)
def insert_checkpoint(
    slug: str, session_id: int, payload: schemas.InsertCheckpointRequest,
    db: Session = Depends(get_project_db), _user: models.User = Depends(require_tester),
):
    """Tester-inserted manual checkpoint -- a direct user-session action,
    not a DOM event the runner observed, so it doesn't need a lease."""
    session = _get_session(db, session_id)
    if session.status not in ("RECORDING", "PAUSED"):
        raise HTTPException(status_code=400, detail=f"Can only insert a checkpoint while recording (current status: {session.status})")
    if not payload.checkpoint_instructions.strip():
        raise HTTPException(status_code=400, detail="checkpoint_instructions is required")
    max_seq = (
        db.query(models.RecordedStep.sequence_no)
        .filter(models.RecordedStep.recording_session_id == session_id)
        .order_by(models.RecordedStep.sequence_no.desc())
        .first()
    )
    next_seq = (max_seq[0] + 1) if max_seq else 1
    step = models.RecordedStep(
        recording_session_id=session_id, sequence_no=next_seq, step_type="MANUAL_CHECKPOINT",
        checkpoint_instructions=payload.checkpoint_instructions,
    )
    db.add(step)
    db.commit()
    db.refresh(step)
    return step


# ---------- reviewing / editing the captured buffer ----------


@router.put("/{session_id}/steps/{step_id}", response_model=schemas.RecordedStepOut)
def update_recorded_step(
    slug: str, session_id: int, step_id: int, payload: schemas.RecordedStepUpdate,
    db: Session = Depends(get_project_db), _user: models.User = Depends(require_tester),
):
    session = _get_session(db, session_id)
    if session.status not in ("STOPPED", "PAUSED"):
        raise HTTPException(status_code=400, detail="Recorded steps can only be edited once the session is STOPPED (or while PAUSED)")
    step = db.query(models.RecordedStep).filter(models.RecordedStep.id == step_id, models.RecordedStep.recording_session_id == session_id).first()
    if not step:
        raise HTTPException(status_code=404, detail="Recorded step not found")
    updates = payload.model_dump(exclude_unset=True)
    for key, value in updates.items():
        setattr(step, key, value)
    step.needs_review = False  # an explicit tester edit resolves the flag
    db.commit()
    db.refresh(step)
    return step


@router.delete("/{session_id}/steps/{step_id}")
def delete_recorded_step(slug: str, session_id: int, step_id: int, db: Session = Depends(get_project_db), _user: models.User = Depends(require_tester)):
    session = _get_session(db, session_id)
    if session.status not in ("STOPPED", "PAUSED"):
        raise HTTPException(status_code=400, detail="Recorded steps can only be deleted once the session is STOPPED (or while PAUSED)")
    step = db.query(models.RecordedStep).filter(models.RecordedStep.id == step_id, models.RecordedStep.recording_session_id == session_id).first()
    if not step:
        raise HTTPException(status_code=404, detail="Recorded step not found")
    db.delete(step)
    db.commit()
    return {"ok": True}


@router.post("/{session_id}/steps/reorder", response_model=list[schemas.RecordedStepOut])
def reorder_recorded_steps(
    slug: str, session_id: int, payload: schemas.RecordedStepReorderRequest,
    db: Session = Depends(get_project_db), _user: models.User = Depends(require_tester),
):
    session = _get_session(db, session_id)
    if session.status != "STOPPED":
        raise HTTPException(status_code=400, detail="Recorded steps can only be reordered once the session is STOPPED")
    steps = {s.id: s for s in db.query(models.RecordedStep).filter(models.RecordedStep.recording_session_id == session_id).all()}
    if set(payload.step_ids_in_order) != set(steps.keys()):
        raise HTTPException(status_code=400, detail="step_ids_in_order must contain exactly this session's current recorded step ids")
    for i, step_id in enumerate(payload.step_ids_in_order, start=1):
        steps[step_id].sequence_no = i
    db.commit()
    return (
        db.query(models.RecordedStep)
        .filter(models.RecordedStep.recording_session_id == session_id)
        .order_by(models.RecordedStep.sequence_no)
        .all()
    )


@router.post("/{session_id}/steps/{step_id}/test-locator", response_model=schemas.RecordedStepOut)
def request_locator_test(slug: str, session_id: int, step_id: int, db: Session = Depends(get_project_db), _user: models.User = Depends(require_tester)):
    session = _get_session(db, session_id)
    if session.status not in ("RECORDING", "PAUSED"):
        raise HTTPException(status_code=400, detail="Locator testing requires the recording browser to still be alive (session RECORDING or PAUSED)")
    step = db.query(models.RecordedStep).filter(models.RecordedStep.id == step_id, models.RecordedStep.recording_session_id == session_id).first()
    if not step:
        raise HTTPException(status_code=404, detail="Recorded step not found")
    step.locator_test_requested = True
    step.locator_test_result_json = None
    db.commit()
    db.refresh(step)
    return step


@router.post("/{session_id}/save-as-draft", response_model=schemas.WorkflowRevisionOut)
def save_as_draft(
    slug: str, session_id: int, payload: schemas.SaveAsDraftRequest,
    db: Session = Depends(get_project_db), user: models.User = Depends(require_tester),
):
    """Reuses HYB-1's own revision/step creation logic one field at a
    time -- a saved recording is indistinguishable from a hand-built
    draft, not a parallel code path."""
    session = _get_session(db, session_id)
    if session.status != "STOPPED":
        raise HTTPException(status_code=400, detail=f"Can only save a STOPPED session as a draft (current status: {session.status})")

    recorded_steps = (
        db.query(models.RecordedStep)
        .filter(models.RecordedStep.recording_session_id == session_id)
        .order_by(models.RecordedStep.sequence_no)
        .all()
    )
    if not recorded_steps:
        raise HTTPException(status_code=400, detail="Cannot save an empty recording as a draft")

    existing = (
        db.query(models.WorkflowRevision)
        .filter(models.WorkflowRevision.workflow_id == session.workflow_id, models.WorkflowRevision.revision_label == payload.revision_label)
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="A revision with that label already exists for this workflow")

    max_sort = (
        db.query(models.WorkflowRevision.revision_number_sort)
        .filter(models.WorkflowRevision.workflow_id == session.workflow_id)
        .order_by(models.WorkflowRevision.revision_number_sort.desc())
        .first()
    )
    next_sort = (max_sort[0] + 1) if max_sort else 1

    revision = models.WorkflowRevision(
        workflow_id=session.workflow_id, revision_label=payload.revision_label, revision_number_sort=next_sort,
        status="DRAFT", change_summary=payload.change_summary or f"Recorded via session {session.id}", created_by=user.email,
    )
    db.add(revision)
    db.flush()

    for i, rec in enumerate(recorded_steps, start=1):
        fields = dict(
            step_type=rec.step_type, description=rec.description, locator_strategy=rec.locator_strategy,
            locator_value=rec.locator_value, locator_fallbacks_json=rec.locator_fallbacks_json,
            locator_source="RECORDER", input_value=rec.input_value, is_sensitive=rec.is_sensitive,
            expected_value=rec.expected_value, checkpoint_instructions=rec.checkpoint_instructions,
            evidence_policy="OPTIONAL" if rec.step_type == "SCREENSHOT" else "NONE",
        )
        # Reuses HYB-1's exact step-field validation (locator requirements
        # per step type, sensitive-value-must-be-a-placeholder rule) --
        # a recorded step must pass the same bar a manually-typed one does.
        _validate_step_fields(fields["step_type"], fields)
        db.add(models.WorkflowStep(revision_id=revision.id, sequence_no=i, **fields))

    session.status = "SAVED"
    db.commit()
    db.refresh(revision)
    return revision


# ---------- runner-facing: claim / heartbeat / append steps / locator-test result ----------


@router.post("/claim")
def claim_session(slug: str, db: Session = Depends(get_project_db), runner: models.RunnerToken = Depends(get_current_runner)):
    _expire_stale_leases(db)
    session = (
        db.query(models.RecordingSession)
        .filter(models.RecordingSession.status == "REQUESTED")
        .order_by(models.RecordingSession.created_at.asc())
        .first()
    )
    if not session:
        return {"claimed": False}

    lease_token = uuid.uuid4().hex
    session.status = "CLAIMED"
    session.runner_id = runner.id
    session.lease_token = lease_token
    session.lease_expires_at = datetime.utcnow() + timedelta(seconds=LEASE_DURATION_SECONDS)
    db.commit()
    db.refresh(session)
    return {
        "claimed": True,
        "session": schemas.RecordingSessionOut.model_validate(session).model_dump(mode="json"),
        "lease_token": lease_token,
    }


@router.post("/{session_id}/recording-started", response_model=schemas.RecordingSessionOut)
def mark_recording_started(slug: str, session_id: int, lease_token: str, db: Session = Depends(get_project_db), runner: models.RunnerToken = Depends(get_current_runner)):
    """Runner calls this once its browser has actually launched and the
    in-page listener is attached -- the session only becomes RECORDING
    (and thus poll-visible as "live" to the tester's UI) once that's
    genuinely true, not the instant it was claimed."""
    session = _get_session(db, session_id)
    _require_lease(session, runner, lease_token)
    if session.status == "CLAIMED":
        session.status = "RECORDING"
        db.commit()
        db.refresh(session)
    return session


@router.post("/{session_id}/heartbeat", response_model=schemas.RecordingSessionOut)
def heartbeat(slug: str, session_id: int, payload: schemas.RecorderHeartbeatRequest, db: Session = Depends(get_project_db), runner: models.RunnerToken = Depends(get_current_runner)):
    _expire_stale_leases(db)
    session = _get_session(db, session_id)
    if session.status in models.RECORDING_SESSION_LEASED_STATUSES:
        _require_lease(session, runner, payload.lease_token)
        session.lease_expires_at = datetime.utcnow() + timedelta(seconds=LEASE_DURATION_SECONDS)
        db.commit()
        db.refresh(session)
    return session


@router.post("/{session_id}/steps", response_model=schemas.RecordedStepOut)
def append_recorded_step(slug: str, session_id: int, payload: schemas.RecordedStepCreate, db: Session = Depends(get_project_db), runner: models.RunnerToken = Depends(get_current_runner)):
    session = _get_session(db, session_id)
    _require_lease(session, runner, payload.lease_token)
    if session.status not in ("RECORDING",):
        raise HTTPException(status_code=400, detail=f"Cannot append a step while the session is {session.status} (must be RECORDING)")

    if payload.idempotency_key:
        # Not a DB-level unique constraint here (unlike RunnerExecutionEvent) --
        # the recorder buffer is small and edited interactively, so a
        # simple existence check is sufficient and keeps step ordering
        # (sequence_no) simpler to reason about than a nullable-unique index.
        dup = (
            db.query(models.RecordedStep)
            .filter(models.RecordedStep.recording_session_id == session_id, models.RecordedStep.review_note == f"idem:{payload.idempotency_key}")
            .first()
        )
        if dup:
            return dup

    fields = payload.model_dump(exclude={"lease_token", "idempotency_key"})
    if payload.step_type not in models.WORKFLOW_STEP_TYPES:
        raise HTTPException(status_code=400, detail=f"step_type must be one of {models.WORKFLOW_STEP_TYPES}")
    if fields.get("is_sensitive") and fields.get("input_value"):
        raise HTTPException(status_code=400, detail="A sensitive recorded step must never carry a real input_value")

    max_seq = (
        db.query(models.RecordedStep.sequence_no)
        .filter(models.RecordedStep.recording_session_id == session_id)
        .order_by(models.RecordedStep.sequence_no.desc())
        .first()
    )
    next_seq = (max_seq[0] + 1) if max_seq else 1
    step = models.RecordedStep(recording_session_id=session_id, sequence_no=next_seq, **fields)
    db.add(step)
    db.commit()
    db.refresh(step)
    return step


@router.get("/{session_id}/pending-locator-tests", response_model=list[schemas.RecordedStepOut])
def list_pending_locator_tests(slug: str, session_id: int, lease_token: str, db: Session = Depends(get_project_db), runner: models.RunnerToken = Depends(get_current_runner)):
    session = _get_session(db, session_id)
    _require_lease(session, runner, lease_token)
    return (
        db.query(models.RecordedStep)
        .filter(models.RecordedStep.recording_session_id == session_id, models.RecordedStep.locator_test_requested == True)  # noqa: E712
        .all()
    )


@router.post("/{session_id}/steps/{step_id}/locator-test-result", response_model=schemas.RecordedStepOut)
def submit_locator_test_result(slug: str, session_id: int, step_id: int, payload: schemas.LocatorTestResultSubmit, db: Session = Depends(get_project_db), runner: models.RunnerToken = Depends(get_current_runner)):
    session = _get_session(db, session_id)
    _require_lease(session, runner, payload.lease_token)
    step = db.query(models.RecordedStep).filter(models.RecordedStep.id == step_id, models.RecordedStep.recording_session_id == session_id).first()
    if not step:
        raise HTTPException(status_code=404, detail="Recorded step not found")
    step.locator_test_requested = False
    step.locator_test_result_json = json.dumps({"matched_count": payload.matched_count, "ok": payload.ok, "message": payload.message})
    db.commit()
    db.refresh(step)
    return step