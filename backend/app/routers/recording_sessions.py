"""HYB-3: browser workflow recorder session protocol.

Recording normally happens in the tester-selected tab through the
QA-Again browser extension. The legacy claim/lease protocol remains for
compatibility, while both paths write the same reviewable candidate
RecordedStep rows and never auto-publish a workflow revision.
"""
import base64
import json
import secrets
import uuid
from datetime import datetime, timedelta
from urllib.parse import urlsplit

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

    # ADR-HYB-002: an extension-mode session (no lease_token/runner_id at
    # all) goes stale the same honest way -- its bound authorization
    # expired or hit its hard cap without the extension stopping the
    # session cleanly first (e.g. the tester closed the tab/browser).
    stale_ext = (
        db.query(models.RecordingSession)
        .join(
            models.RecordingSessionAuthorization,
            models.RecordingSessionAuthorization.id == models.RecordingSession.extension_authorization_id,
        )
        .filter(
            models.RecordingSession.status.in_(models.RECORDING_SESSION_LEASED_STATUSES),
            models.RecordingSessionAuthorization.revoked == False,  # noqa: E712
            (models.RecordingSessionAuthorization.expires_at < now) | (models.RecordingSessionAuthorization.hard_cap_at < now),
        )
        .all()
    )
    for session in stale_ext:
        session.status = "RUNNER_LOST"
    if stale or stale_ext:
        db.commit()


def _issue_extension_authorization(db: Session, session_id: int, issued_by: str) -> tuple[str, models.RecordingSessionAuthorization]:
    raw_token = secrets.token_urlsafe(32)
    now = datetime.utcnow()
    record = models.RecordingSessionAuthorization(
        recording_session_id=session_id,
        token_hash=_hash_token(raw_token),
        issued_by=issued_by,
        expires_at=now + timedelta(seconds=models.RECORDING_SESSION_AUTH_DURATION_SECONDS),
        hard_cap_at=now + timedelta(seconds=models.RECORDING_SESSION_AUTH_HARD_CAP_SECONDS),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return raw_token, record


def _get_valid_extension_auth(db: Session, session_id: int, raw_token: str) -> models.RecordingSessionAuthorization:
    now = datetime.utcnow()
    auth = (
        db.query(models.RecordingSessionAuthorization)
        .filter(
            models.RecordingSessionAuthorization.recording_session_id == session_id,
            models.RecordingSessionAuthorization.token_hash == _hash_token(raw_token),
            models.RecordingSessionAuthorization.revoked == False,  # noqa: E712
        )
        .first()
    )
    if not auth or auth.expires_at < now or auth.hard_cap_at < now:
        raise HTTPException(status_code=401, detail="Invalid, expired, or revoked extension recording authorization")
    return auth


def _authorize_recorder_actor(
    request: Request,
    db: Session,
    master_db: Session,
    session: models.RecordingSession,
    lease_token: str | None,
    extension_token: str | None,
) -> str:
    """Used by the endpoints an active recorder (either mode) calls
    while capturing: /steps, /heartbeat, pending-locator-tests,
    locator-test-result. Exactly one of lease_token (Playwright-mode
    runner) or extension_token (extension mode) must be a valid,
    scoped credential. Returns 'RUNNER' or 'EXTENSION'."""
    if extension_token:
        _get_valid_extension_auth(db, session.id, extension_token)
        return "EXTENSION"
    if lease_token:
        raw_token = request.headers.get("X-Runner-Token")
        if not raw_token:
            raise HTTPException(status_code=401, detail="Missing X-Runner-Token header")
        runner = (
            master_db.query(models.RunnerToken)
            .filter(models.RunnerToken.token_hash == _hash_token(raw_token), models.RunnerToken.revoked == False)  # noqa: E712
            .first()
        )
        if not runner:
            raise HTTPException(status_code=401, detail="Invalid or revoked runner token")
        runner.last_heartbeat_at = datetime.utcnow()
        master_db.commit()
        _require_lease(session, runner, lease_token)
        return "RUNNER"
    raise HTTPException(status_code=401, detail="Provide lease_token (Playwright-mode runner) or extension_token (extension mode)")


def _authorize_human_or_extension(
    request: Request,
    db: Session,
    master_db: Session,
    session: models.RecordingSession,
    extension_token: str | None,
) -> str:
    """Used by the tester-facing controls (pause/resume/stop/undo) so
    the extension popup can call them directly with its own short-lived,
    session-scoped token -- never the tester's full JWT. Falls back to
    the normal authenticated user session when no extension_token is
    given (QA-Again's own UI)."""
    if extension_token:
        _get_valid_extension_auth(db, session.id, extension_token)
        return "EXTENSION"
    user = get_current_user(request=request, db=master_db)
    if user.role not in ("ADMIN", "TESTER"):
        raise HTTPException(status_code=403, detail=f"Role '{user.role}' is not permitted to perform this action")
    return user.email


def _step_target_hint(locator_strategy: str | None, locator_value: str | None) -> str:
    """Short human-readable element description for a save-as-draft
    validation error's "Step N (...)" prefix -- ROLE values are stored
    as "role:accessible name" (see extension/content.js), so show just
    the name; other strategies are already human-readable as captured."""
    if not locator_value:
        return ""
    if locator_strategy == "ROLE" and ":" in locator_value:
        return locator_value.split(":", 1)[1]
    return locator_value


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
def pause_session(
    slug: str, session_id: int, request: Request, extension_token: str | None = None,
    db: Session = Depends(get_project_db), master_db: Session = Depends(get_master_db),
):
    session = _get_session(db, session_id)
    _authorize_human_or_extension(request, db, master_db, session, extension_token)
    if session.status != "RECORDING":
        raise HTTPException(status_code=400, detail=f"Can only pause a RECORDING session (current status: {session.status})")
    session.status = "PAUSED"
    db.commit()
    db.refresh(session)
    return session


@router.post("/{session_id}/resume", response_model=schemas.RecordingSessionOut)
def resume_session(
    slug: str, session_id: int, request: Request, extension_token: str | None = None,
    db: Session = Depends(get_project_db), master_db: Session = Depends(get_master_db),
):
    session = _get_session(db, session_id)
    _authorize_human_or_extension(request, db, master_db, session, extension_token)
    if session.status != "PAUSED":
        raise HTTPException(status_code=400, detail=f"Can only resume a PAUSED session (current status: {session.status})")
    session.status = "RECORDING"
    db.commit()
    db.refresh(session)
    return session


@router.post("/{session_id}/stop", response_model=schemas.RecordingSessionOut)
def stop_session(
    slug: str, session_id: int, request: Request, extension_token: str | None = None,
    db: Session = Depends(get_project_db), master_db: Session = Depends(get_master_db),
):
    session = _get_session(db, session_id)
    _authorize_human_or_extension(request, db, master_db, session, extension_token)
    if session.status not in ("RECORDING", "PAUSED", "CLAIMED"):
        raise HTTPException(status_code=400, detail=f"Cannot stop a session in status {session.status}")
    session.status = "STOPPED"
    # ADR-HYB-002: revoke the extension authorization immediately on stop
    # -- it must never remain usable after the tester has ended the
    # session, matching "revoke authorization when the session stops or
    # expires".
    if session.extension_authorization_id:
        auth = db.query(models.RecordingSessionAuthorization).filter(models.RecordingSessionAuthorization.id == session.extension_authorization_id).first()
        if auth:
            auth.revoked = True
            auth.revoked_at = datetime.utcnow()
    db.commit()
    db.refresh(session)
    return session


@router.post("/{session_id}/undo-last-step", response_model=schemas.RecordingSessionDetailOut)
def undo_last_step(
    slug: str, session_id: int, request: Request, extension_token: str | None = None,
    db: Session = Depends(get_project_db), master_db: Session = Depends(get_master_db),
):
    """Removes exactly the single most-recently-captured step, live,
    while still RECORDING/PAUSED -- callable repeatedly to walk back to
    an empty buffer. Available from both the extension popup and
    QA-Again's own RecordingPanel (see docs/hybrid/
    CHROME_EXTENSION_RECORDER.md's "Undo last step" section). Distinct
    from DELETE .../steps/{id} (any step, only once STOPPED, used
    during considered review) -- this is the in-the-moment correction
    control."""
    session = _get_session(db, session_id)
    _authorize_human_or_extension(request, db, master_db, session, extension_token)
    if session.status not in ("RECORDING", "PAUSED"):
        raise HTTPException(status_code=400, detail=f"Can only undo the last step while RECORDING or PAUSED (current status: {session.status})")
    last_step = (
        db.query(models.RecordedStep)
        .filter(models.RecordedStep.recording_session_id == session_id)
        .order_by(models.RecordedStep.sequence_no.desc())
        .first()
    )
    if not last_step:
        raise HTTPException(status_code=400, detail="No recorded steps to undo -- already at the start")
    db.delete(last_step)
    db.commit()
    return _to_detail(db, session)


@router.post("/{session_id}/discard", response_model=schemas.RecordingSessionOut)
def discard_session(slug: str, session_id: int, db: Session = Depends(get_project_db), _user: models.User = Depends(require_tester)):
    session = _get_session(db, session_id)
    if session.status == "SAVED":
        raise HTTPException(status_code=400, detail="Cannot discard a session that was already saved as a draft")
    db.query(models.RecordedStep).filter(models.RecordedStep.recording_session_id == session_id).delete()
    session.status = "DISCARDED"
    if session.extension_authorization_id:
        auth = db.query(models.RecordingSessionAuthorization).filter(models.RecordingSessionAuthorization.id == session.extension_authorization_id).first()
        if auth:
            auth.revoked = True
            auth.revoked_at = datetime.utcnow()
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


@router.post("/{session_id}/insert-wait", response_model=schemas.RecordedStepOut)
def insert_wait(
    slug: str, session_id: int, payload: schemas.InsertWaitRequest,
    db: Session = Depends(get_project_db), _user: models.User = Depends(require_tester),
):
    """Tester-inserted timed pause -- same "direct user-session action,
    no lease needed" shape as insert_checkpoint above."""
    session = _get_session(db, session_id)
    if session.status not in ("RECORDING", "PAUSED"):
        raise HTTPException(status_code=400, detail=f"Can only insert a wait while recording (current status: {session.status})")
    if payload.duration_ms <= 0:
        raise HTTPException(status_code=400, detail="duration_ms must be positive")
    max_seq = (
        db.query(models.RecordedStep.sequence_no)
        .filter(models.RecordedStep.recording_session_id == session_id)
        .order_by(models.RecordedStep.sequence_no.desc())
        .first()
    )
    next_seq = (max_seq[0] + 1) if max_seq else 1
    step = models.RecordedStep(
        recording_session_id=session_id, sequence_no=next_seq, step_type="WAIT",
        input_value=str(payload.duration_ms),
    )
    db.add(step)
    db.commit()
    db.refresh(step)
    return step


@router.post("/{session_id}/insert-screenshot", response_model=schemas.RecordedStepOut)
def insert_screenshot(
    slug: str, session_id: int,
    db: Session = Depends(get_project_db), _user: models.User = Depends(require_tester),
):
    session = _get_session(db, session_id)
    if session.status not in ("RECORDING", "PAUSED"):
        raise HTTPException(status_code=400, detail=f"Can only insert a screenshot while recording (current status: {session.status})")
    max_seq = (
        db.query(models.RecordedStep.sequence_no)
        .filter(models.RecordedStep.recording_session_id == session_id)
        .order_by(models.RecordedStep.sequence_no.desc())
        .first()
    )
    step = models.RecordedStep(
        recording_session_id=session_id,
        sequence_no=(max_seq[0] + 1) if max_seq else 1,
        step_type="SCREENSHOT",
        description="Capture screenshot",
    )
    db.add(step)
    db.commit()
    db.refresh(step)
    return step


@router.post("/{session_id}/steps/{step_id}/insert-screenshot-after", response_model=schemas.RecordedStepOut)
def insert_screenshot_after_step(
    slug: str, session_id: int, step_id: int,
    db: Session = Depends(get_project_db), _user: models.User = Depends(require_tester),
):
    session = _get_session(db, session_id)
    if session.status not in ("STOPPED", "PAUSED"):
        raise HTTPException(status_code=400, detail="Screenshots can be inserted after an action once recording is stopped (or paused)")
    target = db.query(models.RecordedStep).filter(
        models.RecordedStep.id == step_id,
        models.RecordedStep.recording_session_id == session_id,
    ).first()
    if not target:
        raise HTTPException(status_code=404, detail="Recorded step not found")
    later_steps = db.query(models.RecordedStep).filter(
        models.RecordedStep.recording_session_id == session_id,
        models.RecordedStep.sequence_no > target.sequence_no,
    ).order_by(models.RecordedStep.sequence_no.desc()).all()
    for later in later_steps:
        later.sequence_no += 1
    screenshot = models.RecordedStep(
        recording_session_id=session_id,
        sequence_no=target.sequence_no + 1,
        step_type="SCREENSHOT",
        description="Capture screenshot",
    )
    db.add(screenshot)
    db.commit()
    db.refresh(screenshot)
    return screenshot


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
        # A recording can have many steps, so a validation failure here
        # needs to say WHICH one -- unlike the single-step create/update
        # forms, where the step being edited is already on screen.
        try:
            _validate_step_fields(fields["step_type"], fields)
        except HTTPException as exc:
            hint = _step_target_hint(rec.locator_strategy, rec.locator_value)
            where = f' targeting "{hint}"' if hint else ""
            # exc.detail already ends with the fix ("...or delete this
            # step.") -- just prefix with which step, in the same order
            # they appear in the review list below.
            raise HTTPException(status_code=400, detail=f"Step {i} ({rec.step_type}{where}): {exc.detail}")
        db.add(models.WorkflowStep(revision_id=revision.id, sequence_no=i, **fields))

    session.status = "SAVED"
    db.commit()
    db.refresh(revision)
    return revision


# ---------- ADR-HYB-002: Chrome extension authorization ----------


@router.post("/{session_id}/authorize-extension", response_model=schemas.ExtensionAuthorizationOut)
def authorize_extension(
    slug: str, session_id: int, request: Request, db: Session = Depends(get_project_db), user: models.User = Depends(require_tester),
):
    """Mints a short-lived, session-scoped authorization the extension
    presents on every subsequent call -- never the tester's own JWT,
    never the global RunnerToken. Called from QA-Again's own UI (the
    tester's real login session), which then hands the raw token to the
    extension out-of-band via the pairing code the tester copies into
    the popup. The session must still be REQUESTED -- an authorization
    is minted once, for the one session it's about to connect."""
    session = _get_session(db, session_id)
    if session.status != "REQUESTED":
        raise HTTPException(status_code=400, detail=f"Can only authorize a REQUESTED session (current status: {session.status})")
    raw_token, record = _issue_extension_authorization(db, session_id, user.email)

    # One-paste pairing code: everything the extension popup previously
    # required as four hand-typed fields, bundled into a single base64
    # string. request.base_url reflects the Host (and X-Forwarded-*
    # via the proxy-headers middleware) the frontend actually reached
    # this backend on -- through the Vite dev proxy (changeOrigin) that
    # is the backend's own 127.0.0.1:8000, and in production the real
    # deployed backend origin, so the code works in both without the
    # tester ever typing a URL.
    backend_url = str(request.base_url).rstrip("/")
    pairing_payload = json.dumps(
        {"backendUrl": backend_url, "projectSlug": slug, "sessionId": session_id, "token": raw_token}
    )
    pairing_code = base64.b64encode(pairing_payload.encode("utf-8")).decode("ascii")

    return schemas.ExtensionAuthorizationOut(
        id=record.id, recording_session_id=session_id, token=raw_token, pairing_code=pairing_code,
        expires_at=record.expires_at, hard_cap_at=record.hard_cap_at,
    )


@router.post("/{session_id}/extension-connect", response_model=schemas.RecordingSessionOut)
def extension_connect(slug: str, session_id: int, payload: schemas.ExtensionConnectRequest, db: Session = Depends(get_project_db)):
    """Extension-mode equivalent of /claim + /recording-started combined
    -- there is no FIFO-poll claim step here (the token is already
    scoped to this exact session), so connecting goes straight to
    RECORDING once the extension's content script confirms it's
    attached (mirrors the Playwright mode's own "only RECORDING once
    genuinely true" discipline)."""
    session = _get_session(db, session_id)
    auth = _get_valid_extension_auth(db, session_id, payload.extension_token)
    if session.status != "REQUESTED":
        raise HTTPException(status_code=400, detail=f"This session is not awaiting connection (current status: {session.status})")
    if payload.target_url:
        parsed_target = urlsplit(payload.target_url)
        if parsed_target.scheme not in ("http", "https") or not parsed_target.netloc:
            raise HTTPException(status_code=400, detail="The selected tab must be an http or https page")
        session.target_url = payload.target_url
        db.add(models.RecordedStep(
            recording_session_id=session.id,
            sequence_no=1,
            step_type="NAVIGATE",
            input_value=payload.target_url,
            page_context=parsed_target.path or "/",
        ))
    session.status = "RECORDING"
    session.extension_authorization_id = auth.id
    db.commit()
    db.refresh(session)
    return session


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
def heartbeat(
    slug: str, session_id: int, payload: schemas.RecorderHeartbeatRequest, request: Request,
    db: Session = Depends(get_project_db), master_db: Session = Depends(get_master_db),
):
    _expire_stale_leases(db)
    session = _get_session(db, session_id)
    if session.status in models.RECORDING_SESSION_LEASED_STATUSES:
        actor = _authorize_recorder_actor(request, db, master_db, session, payload.lease_token, payload.extension_token)
        if actor == "RUNNER":
            session.lease_expires_at = datetime.utcnow() + timedelta(seconds=LEASE_DURATION_SECONDS)
        else:
            # ADR-HYB-002: renew the extension's own short-lived
            # authorization, never past its hard cap -- a genuinely
            # short-lived credential, not indefinitely renewable.
            auth = db.query(models.RecordingSessionAuthorization).filter(models.RecordingSessionAuthorization.id == session.extension_authorization_id).first()
            now = datetime.utcnow()
            auth.expires_at = min(now + timedelta(seconds=models.RECORDING_SESSION_AUTH_DURATION_SECONDS), auth.hard_cap_at)
        db.commit()
        db.refresh(session)
    return session


@router.post("/{session_id}/steps", response_model=schemas.RecordedStepOut)
def append_recorded_step(
    slug: str, session_id: int, payload: schemas.RecordedStepCreate, request: Request,
    db: Session = Depends(get_project_db), master_db: Session = Depends(get_master_db),
):
    session = _get_session(db, session_id)
    _authorize_recorder_actor(request, db, master_db, session, payload.lease_token, payload.extension_token)
    if session.status not in ("RECORDING",):
        raise HTTPException(status_code=400, detail=f"Cannot append a step while the session is {session.status} (must be RECORDING)")

    if payload.idempotency_key:
        # Not a DB-level unique constraint here (unlike RunnerExecutionEvent) --
        # the recorder buffer is small and edited interactively, so a
        # simple existence check is sufficient and keeps step ordering
        # (sequence_no) simpler to reason about than a nullable-unique index.
        dup = (
            db.query(models.RecordedStep)
            .filter(models.RecordedStep.recording_session_id == session_id, models.RecordedStep.idempotency_key == payload.idempotency_key)
            .first()
        )
        if dup:
            return dup

    fields = payload.model_dump(exclude={"lease_token", "extension_token"})
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
def list_pending_locator_tests(
    slug: str, session_id: int, request: Request, lease_token: str | None = None, extension_token: str | None = None,
    db: Session = Depends(get_project_db), master_db: Session = Depends(get_master_db),
):
    session = _get_session(db, session_id)
    _authorize_recorder_actor(request, db, master_db, session, lease_token, extension_token)
    return (
        db.query(models.RecordedStep)
        .filter(models.RecordedStep.recording_session_id == session_id, models.RecordedStep.locator_test_requested == True)  # noqa: E712
        .all()
    )


@router.post("/{session_id}/steps/{step_id}/locator-test-result", response_model=schemas.RecordedStepOut)
def submit_locator_test_result(
    slug: str, session_id: int, step_id: int, payload: schemas.LocatorTestResultSubmit, request: Request,
    db: Session = Depends(get_project_db), master_db: Session = Depends(get_master_db),
):
    session = _get_session(db, session_id)
    _authorize_recorder_actor(request, db, master_db, session, payload.lease_token, payload.extension_token)
    step = db.query(models.RecordedStep).filter(models.RecordedStep.id == step_id, models.RecordedStep.recording_session_id == session_id).first()
    if not step:
        raise HTTPException(status_code=404, detail="Recorded step not found")
    step.locator_test_requested = False
    step.locator_test_result_json = json.dumps({"matched_count": payload.matched_count, "ok": payload.ok, "message": payload.message})
    db.commit()
    db.refresh(step)
    return step
