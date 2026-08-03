"""HYB-2: runner job-claim protocol and structured execution history.

Job protocol (docs/Autonomous hybird prompt.md's HYB-2 section):
  1. A human/system queues a run against a PUBLISHED workflow revision.
  2. A runner authenticates (X-Runner-Token) and POSTs /claim -- this is
     the runner initiating outbound, never the backend calling into the
     runner (see docs/hybrid/HYB-0-GAP-ANALYSIS.md's outbound-only rule,
     which still applies unchanged).
  3. The claim grants a time-limited lease (lease_token + expiry). Every
     subsequent runner call for that run must present the same
     lease_token, both to prove ownership and to make a second runner
     racing for the same "already claimed" run get rejected outright.
  4. The runner renews the lease via /heartbeat while working; if it
     stops (crash, network loss), the lease silently expires and a lazy
     sweep (`_expire_stale_leases`, invoked at the top of every endpoint
     here) marks the run RUNNER_LOST -- no cron/scheduler needed.
  5. Structured step results land in WorkflowStepRun rows (not just the
     raw RunnerExecutionEvent log), and events support an idempotency
     key so a retried POST after a network blip is a no-op, not a
     duplicate.
"""
import base64
import binascii
import hashlib
import json
import logging
import os
import secrets
import time
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Response
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_project_db, get_master_db
from ..evidence_utils import sniff_image, MAX_EVIDENCE_SIZE_BYTES
from ..auth import get_current_user, require_tester, require_admin, get_current_runner, issue_runner_token, _hash_token
from ..quota import quota_status
from ..rate_limit import limiter
from ..storage import EvidenceStorage, get_evidence_storage
from ..execution_dispatch import ExecutionDispatchError, dispatch_workflow_run, execution_provider
from .workflows import _validate_step_fields

logger = logging.getLogger("workflow_runs")

router = APIRouter(prefix="/api/{slug}/workflow-runs", tags=["workflow-runs"])
BROWSER_AUTH_TTL = timedelta(minutes=15)


# ---------- shared helpers ----------


def _expire_stale_leases(db: Session):
    """Covers both the active-execution lease (WORKFLOW_RUN_LEASED_STATUSES,
    60s) and the HYB-4 paused lease (WORKFLOW_RUN_PAUSED_LEASE_STATUSES,
    300s) -- a runner that stops heartbeating while WAITING_FOR_HUMAN or
    RESUMING is just as lost as one that stops mid-step, only on a
    longer timeout. Either way this never touches an existing
    WorkflowCheckpointDecision row -- if a human hadn't decided yet, none
    exists; if one already exists (PASS -> RESUMING) it's left exactly as
    recorded, immutable, and simply never gets acted on by a runner that
    isn't coming back."""
    now = datetime.utcnow()
    stale = (
        db.query(models.WorkflowRun)
        .filter(
            models.WorkflowRun.status.in_(models.WORKFLOW_RUN_LEASED_STATUSES + models.WORKFLOW_RUN_PAUSED_LEASE_STATUSES),
            models.WorkflowRun.lease_expires_at.isnot(None),
            models.WorkflowRun.lease_expires_at < now,
        )
        .all()
    )
    for run in stale:
        run.status = "RUNNER_LOST"
        run.ended_at = now
        run.lease_token = None
        run.lease_expires_at = None
        _add_event(db, run.id, "RUNNER_LOST", "SYSTEM")
    if stale:
        db.commit()


def _add_event(db: Session, run_id: int, event_type: str, actor_type: str, idempotency_key: str | None = None, payload_json: str | None = None):
    if event_type not in models.RUNNER_EXEC_EVENT_TYPES:
        raise HTTPException(status_code=400, detail=f"event_type must be one of {models.RUNNER_EXEC_EVENT_TYPES}")
    db.add(
        models.RunnerExecutionEvent(
            workflow_run_id=run_id, event_type=event_type, actor_type=actor_type,
            idempotency_key=idempotency_key, payload_json=payload_json,
        )
    )


def _require_user_or_runner(request: Request, master_db: Session):
    """The runner polls GET /{run_id} to check cancel_requested between
    steps -- it only holds a runner token, never a user cookie/JWT. This
    endpoint is also used by the human-facing run monitoring UI. No
    single FastAPI dependency covers both credential types, so (matching
    hybrid.py's get_run) this checks manually instead."""
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
    # Fall through to normal cookie/JWT user auth.
    get_current_user(request=request, db=master_db)


def _get_run(db: Session, run_id: int) -> models.WorkflowRun:
    run = db.query(models.WorkflowRun).filter(models.WorkflowRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Workflow run not found")
    return run


def _require_lease(run: models.WorkflowRun, runner: models.RunnerToken, lease_token: str):
    if run.runner_id != runner.id or not run.lease_token or run.lease_token != lease_token:
        raise HTTPException(status_code=409, detail="This run is not currently leased to you (claimed by another runner, expired, or already finished)")


def _to_run_out(db: Session, run: models.WorkflowRun) -> schemas.WorkflowRunOut:
    out = schemas.WorkflowRunOut.model_validate(run)
    revision = db.query(models.WorkflowRevision).filter(models.WorkflowRevision.id == run.workflow_revision_id).first()
    if revision:
        out.workflow_revision_label = revision.revision_label
        wf = db.query(models.WorkflowDefinition).filter(models.WorkflowDefinition.id == revision.workflow_id).first()
        if wf:
            out.workflow_name = wf.name
    return out


def _browser_authorization(db: Session, run: models.WorkflowRun, raw_token: str) -> models.WorkflowRunBrowserAuthorization:
    authorization = (
        db.query(models.WorkflowRunBrowserAuthorization)
        .filter(
            models.WorkflowRunBrowserAuthorization.workflow_run_id == run.id,
            models.WorkflowRunBrowserAuthorization.token_hash == _hash_token(raw_token),
            models.WorkflowRunBrowserAuthorization.revoked.is_(False),
        )
        .first()
    )
    if not authorization:
        raise HTTPException(status_code=401, detail="Invalid or revoked browser-test pairing code")
    if authorization.expires_at < datetime.utcnow():
        authorization.revoked = True
        if run.status in ("WAITING_FOR_TARGET", "READY"):
            run.status = "SYSTEM_ERROR"
            run.result_summary = "The browser-test pairing code expired before the test started"
            run.ended_at = datetime.utcnow()
            _add_event(db, run.id, "RUN_COMPLETED", "SYSTEM", payload_json='{"status":"SYSTEM_ERROR","source":"pairing_expired"}')
        db.commit()
        raise HTTPException(status_code=401, detail="Browser-test pairing code expired; prepare the test again")
    return authorization


def _browser_plan_steps(db: Session, run: models.WorkflowRun) -> list[models.WorkflowStep]:
    return (
        db.query(models.WorkflowStep)
        .filter(models.WorkflowStep.revision_id == run.workflow_revision_id, models.WorkflowStep.enabled.is_(True))
        .order_by(models.WorkflowStep.sequence_no)
        .all()
    )


def _dispatch_queued_run(db: Session, master_db: Session, slug: str, run: models.WorkflowRun) -> None:
    """Start ephemeral cloud execution when configured.

    Dispatch happens only after the QUEUED transaction is durable. A provider
    failure is recorded honestly as SYSTEM_ERROR instead of leaving a job that
    appears to be preparing forever.
    """
    runner_token = None
    runner_token_id = None
    try:
        if execution_provider() == "embedded":
            runner_token, token_record = issue_runner_token(master_db, f"one-shot local browser run {slug}/{run.id}")
            runner_token_id = token_record.id
        dispatch_workflow_run(slug, run.id, runner_token=runner_token, runner_token_id=runner_token_id)
    except ExecutionDispatchError as exc:
        run.status = "SYSTEM_ERROR"
        run.result_summary = str(exc)
        run.ended_at = datetime.utcnow()
        db.commit()
        logger.exception("Could not dispatch workflow run %s/%s", slug, run.id)
        raise HTTPException(status_code=503, detail=str(exc)) from exc


# ---------- queue / list / detail (human + runner reads) ----------


@router.post("/browser-prepare", response_model=schemas.WorkflowBrowserPrepareOut)
def prepare_browser_run(
    slug: str,
    payload: schemas.WorkflowBrowserPrepareRequest,
    request: Request,
    db: Session = Depends(get_project_db),
    user: models.User = Depends(require_tester),
):
    """Prepare extension playback without executing anything yet.

    The tester explicitly selects a normal browser tab and presses Start in
    the injected floating controller. Until then the run stays
    WAITING_FOR_TARGET and no page receives automated input.
    """
    revision = db.query(models.WorkflowRevision).filter(models.WorkflowRevision.id == payload.workflow_revision_id).first()
    if not revision:
        raise HTTPException(status_code=404, detail="Workflow revision not found")
    steps = _browser_plan_steps(db, models.WorkflowRun(workflow_revision_id=revision.id))
    if not steps:
        raise HTTPException(status_code=400, detail="Cannot run a revision with no enabled actions")
    for step in steps:
        _validate_step_fields(
            step.step_type,
            {
                "locator_strategy": step.locator_strategy,
                "locator_value": step.locator_value,
                "input_value": step.input_value,
                "expected_value": step.expected_value,
                "checkpoint_instructions": step.checkpoint_instructions,
                "is_sensitive": step.is_sensitive,
                "evidence_policy": step.evidence_policy,
                "repeat_count": step.repeat_count,
            },
        )

    run = models.WorkflowRun(
        workflow_revision_id=revision.id,
        status="WAITING_FOR_TARGET",
        queued_by=user.email,
        is_preview=revision.status != "PUBLISHED",
    )
    db.add(run)
    db.flush()
    raw_token = secrets.token_urlsafe(32)
    expires_at = datetime.utcnow() + BROWSER_AUTH_TTL
    db.add(
        models.WorkflowRunBrowserAuthorization(
            workflow_run_id=run.id,
            token_hash=_hash_token(raw_token),
            expires_at=expires_at,
        )
    )
    _add_event(db, run.id, "RUN_QUEUED", "HUMAN", payload_json='{"mode":"browser_extension"}')
    db.commit()
    db.refresh(run)

    backend_url = os.environ.get("PUBLIC_BACKEND_URL", "").strip() or str(request.base_url).rstrip("/")
    pairing_payload = {
        "mode": "playback",
        "backendUrl": backend_url,
        "projectSlug": slug,
        "runId": run.id,
        "token": raw_token,
    }
    pairing_code = base64.b64encode(json.dumps(pairing_payload, separators=(",", ":")).encode()).decode()
    return schemas.WorkflowBrowserPrepareOut(run=_to_run_out(db, run), pairing_code=pairing_code, expires_at=expires_at)


@router.post("/{run_id}/browser-connect", response_model=schemas.WorkflowBrowserPlanOut)
def connect_browser_run(
    slug: str,
    run_id: int,
    payload: schemas.WorkflowBrowserTokenRequest,
    db: Session = Depends(get_project_db),
):
    run = _get_run(db, run_id)
    authorization = _browser_authorization(db, run, payload.extension_token)
    if run.status not in ("WAITING_FOR_TARGET", "READY"):
        raise HTTPException(status_code=409, detail=f"This test cannot attach to a tab (status: {run.status})")
    if run.status == "WAITING_FOR_TARGET":
        run.status = "READY"
        authorization.connected_at = datetime.utcnow()
        _add_event(db, run.id, "TARGET_ATTACHED", "RUNNER")
        db.commit()
        db.refresh(run)
    return schemas.WorkflowBrowserPlanOut(
        run=_to_run_out(db, run),
        steps=[schemas.WorkflowRunClaimStep.model_validate(step) for step in _browser_plan_steps(db, run)],
    )


@router.post("/{run_id}/browser-start", response_model=schemas.WorkflowRunOut)
def start_browser_run(
    slug: str,
    run_id: int,
    payload: schemas.WorkflowBrowserTokenRequest,
    db: Session = Depends(get_project_db),
):
    run = _get_run(db, run_id)
    _browser_authorization(db, run, payload.extension_token)
    if run.status not in ("READY", "RUNNING"):
        raise HTTPException(status_code=409, detail=f"Select a target tab before starting (status: {run.status})")
    if run.status == "READY":
        run.status = "RUNNING"
        run.started_at = datetime.utcnow()
        _add_event(db, run.id, "RUN_CLAIMED", "RUNNER", payload_json='{"mode":"browser_extension"}')
        db.commit()
        db.refresh(run)
    return _to_run_out(db, run)


@router.post("/{run_id}/browser-status", response_model=schemas.WorkflowRunOut)
def browser_run_status(
    slug: str,
    run_id: int,
    payload: schemas.WorkflowBrowserTokenRequest,
    db: Session = Depends(get_project_db),
):
    run = _get_run(db, run_id)
    _browser_authorization(db, run, payload.extension_token)
    return _to_run_out(db, run)


@router.post("/{run_id}/browser-step", response_model=schemas.WorkflowStepRunOut)
def report_browser_step(
    slug: str,
    run_id: int,
    payload: schemas.WorkflowBrowserStepResultRequest,
    db: Session = Depends(get_project_db),
):
    run = _get_run(db, run_id)
    _browser_authorization(db, run, payload.extension_token)
    if run.status != "RUNNING":
        raise HTTPException(status_code=409, detail=f"This browser test is not running (status: {run.status})")
    if payload.status not in ("PASSED", "FAILED", "SKIPPED"):
        raise HTTPException(status_code=400, detail="Browser step status must be PASSED, FAILED, or SKIPPED")
    if payload.failure_category and payload.failure_category not in models.FAILURE_CATEGORIES:
        raise HTTPException(status_code=400, detail=f"failure_category must be one of {models.FAILURE_CATEGORIES}")
    if payload.duration_ms is not None and (payload.duration_ms < 0 or payload.duration_ms > 86_400_000):
        raise HTTPException(status_code=400, detail="duration_ms must be between 0 and 86400000")
    step = db.query(models.WorkflowStep).filter(
        models.WorkflowStep.id == payload.workflow_step_id,
        models.WorkflowStep.revision_id == run.workflow_revision_id,
    ).first()
    if not step:
        raise HTTPException(status_code=404, detail="Workflow step not found on this run's revision")
    existing = db.query(models.WorkflowStepRun).filter(
        models.WorkflowStepRun.workflow_run_id == run.id,
        models.WorkflowStepRun.workflow_step_id == step.id,
        models.WorkflowStepRun.attempt_number == payload.attempt_number,
    ).first()
    if existing:
        out = schemas.WorkflowStepRunOut.model_validate(existing)
        out.step_type = step.step_type
        out.step_description = step.description
        return out
    now = datetime.utcnow()
    started_at = now - timedelta(milliseconds=payload.duration_ms or 0)
    step_run = models.WorkflowStepRun(
        workflow_run_id=run.id,
        workflow_step_id=step.id,
        sequence_no=step.sequence_no,
        attempt_number=payload.attempt_number,
        status=payload.status,
        outcome=payload.outcome,
        failure_category=payload.failure_category,
        machine_message=payload.machine_message,
        locator_used_json=payload.locator_used_json,
        duration_ms=payload.duration_ms,
        started_at=started_at,
        ended_at=now,
    )
    db.add(step_run)
    event_type = "STEP_FAILED" if payload.status == "FAILED" else "STEP_COMPLETED"
    _add_event(db, run.id, event_type, "RUNNER", payload_json=f'{{"workflow_step_id":{step.id},"status":"{payload.status}"}}')
    db.commit()
    db.refresh(step_run)
    out = schemas.WorkflowStepRunOut.model_validate(step_run)
    out.step_type = step.step_type
    out.step_description = step.description
    return out


@router.post("/{run_id}/browser-screenshot", response_model=schemas.WorkflowRunScreenshotOut)
def upload_browser_screenshot(
    slug: str,
    run_id: int,
    payload: schemas.WorkflowBrowserScreenshotRequest,
    db: Session = Depends(get_project_db),
    master_db: Session = Depends(get_master_db),
    storage: EvidenceStorage = Depends(get_evidence_storage),
):
    """Stores one visible-tab PNG captured by the paired extension."""
    upload_started = time.perf_counter()
    run = _get_run(db, run_id)
    _browser_authorization(db, run, payload.extension_token)
    if run.status != "RUNNING":
        raise HTTPException(status_code=409, detail=f"This browser test is not running (status: {run.status})")
    step = db.query(models.WorkflowStep).filter(
        models.WorkflowStep.id == payload.workflow_step_id,
        models.WorkflowStep.revision_id == run.workflow_revision_id,
    ).first()
    if not step:
        raise HTTPException(status_code=404, detail="Workflow step not found on this run's revision")
    prefix = "data:image/png;base64,"
    if not payload.data_url.startswith(prefix):
        raise HTTPException(status_code=400, detail="Screenshot must be a PNG data URL")
    try:
        content = base64.b64decode(payload.data_url[len(prefix):], validate=True)
    except (ValueError, binascii.Error) as exc:
        raise HTTPException(status_code=400, detail="Screenshot data is not valid base64") from exc
    if not content or len(content) > MAX_EVIDENCE_SIZE_BYTES:
        raise HTTPException(status_code=400, detail=f"Screenshot must be between 1 byte and {MAX_EVIDENCE_SIZE_BYTES // (1024 * 1024)}MB")
    if sniff_image(content) != ("image/png", "png"):
        raise HTTPException(status_code=400, detail="Screenshot is not a valid PNG")

    project = master_db.query(models.Project).filter(models.Project.slug == slug).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if quota_status(project, db)["used_bytes"] + len(content) > project.storage_quota_bytes:
        raise HTTPException(status_code=400, detail="Uploading this screenshot would exceed the project's storage quota")

    digest = hashlib.sha256(content).hexdigest()
    existing = db.query(models.WorkflowRunScreenshot).filter(
        models.WorkflowRunScreenshot.workflow_run_id == run.id,
        models.WorkflowRunScreenshot.workflow_step_id == step.id,
        models.WorkflowRunScreenshot.sha256 == digest,
    ).first()
    if existing:
        return existing
    object_key = f"workflow-screenshots/{slug}/{run.id}/{uuid.uuid4().hex}.png"
    storage.put(object_key, content, "image/png")
    item = models.WorkflowRunScreenshot(
        workflow_run_id=run.id,
        workflow_step_id=step.id,
        object_key=object_key,
        content_type="image/png",
        size_bytes=len(content),
        sha256=digest,
        upload_duration_ms=round((time.perf_counter() - upload_started) * 1000),
    )
    try:
        db.add(item)
        db.commit()
        db.refresh(item)
    except Exception:
        db.rollback()
        storage.delete(object_key)
        raise
    _add_event(db, run.id, "EVIDENCE_UPLOADED", "RUNNER", payload_json=f'{{"screenshot_id":{item.id},"workflow_step_id":{step.id}}}')
    db.commit()
    return item


@router.post("/{run_id}/browser-complete", response_model=schemas.WorkflowRunOut)
def complete_browser_run(
    slug: str,
    run_id: int,
    payload: schemas.WorkflowBrowserCompleteRequest,
    db: Session = Depends(get_project_db),
):
    run = _get_run(db, run_id)
    authorization = _browser_authorization(db, run, payload.extension_token)
    allowed = {"PASSED", "FAILED", "CANCELLED", "BLOCKED", "SYSTEM_ERROR"}
    if payload.status not in allowed:
        raise HTTPException(status_code=400, detail=f"status must be one of {sorted(allowed)}")
    if run.status not in models.WORKFLOW_RUN_TERMINAL_STATUSES:
        run.status = payload.status
        run.result_summary = payload.result_summary
        run.ended_at = datetime.utcnow()
        run.cancel_requested = False
        _add_event(db, run.id, "RUN_COMPLETED", "RUNNER", payload_json=f'{{"status":"{payload.status}","mode":"browser_extension"}}')
    authorization.revoked = True
    db.commit()
    db.refresh(run)
    return _to_run_out(db, run)


@router.post("", response_model=schemas.WorkflowRunOut)
def queue_run(
    slug: str,
    payload: schemas.WorkflowRunCreate,
    db: Session = Depends(get_project_db),
    master_db: Session = Depends(get_master_db),
    user: models.User = Depends(require_tester),
):
    revision = db.query(models.WorkflowRevision).filter(models.WorkflowRevision.id == payload.workflow_revision_id).first()
    if not revision:
        raise HTTPException(status_code=404, detail="Workflow revision not found")
    if revision.status != "PUBLISHED":
        raise HTTPException(status_code=400, detail=f"Only a PUBLISHED workflow revision can be run (current status: {revision.status})")
    if payload.cycle_test_result_id is not None:
        result = db.query(models.CycleTestResult).filter(models.CycleTestResult.id == payload.cycle_test_result_id).first()
        if not result:
            raise HTTPException(status_code=404, detail="cycle_test_result_id does not exist")

    run = models.WorkflowRun(
        workflow_revision_id=revision.id,
        cycle_test_result_id=payload.cycle_test_result_id,
        status="QUEUED",
        queued_by=user.email,
    )
    db.add(run)
    db.flush()
    _add_event(db, run.id, "RUN_QUEUED", "HUMAN")
    db.commit()
    db.refresh(run)
    _dispatch_queued_run(db, master_db, slug, run)
    return _to_run_out(db, run)


@router.post("/preview", response_model=schemas.WorkflowRunOut)
def preview_run(
    slug: str,
    payload: schemas.WorkflowPreviewRunCreate,
    db: Session = Depends(get_project_db),
    master_db: Session = Depends(get_master_db),
    user: models.User = Depends(require_tester),
):
    """Phase E: a tester's own "Test It Now" sanity check -- runs through
    the exact same claim/execute/report-progress path as a real run
    (the runner's /claim doesn't care about revision.status), but
    deliberately skips queue_run's "must be PUBLISHED" gate (the whole
    point is testing a DRAFT before an admin ever publishes it) and can
    never carry a cycle_test_result_id (schemas.WorkflowPreviewRunCreate
    doesn't even accept the field). is_preview=True keeps it out of
    every Track A/B reporting and export query -- a preview never
    becomes part of the audited record, and this endpoint never
    touches a revision's publish status either. Publish stays entirely
    ADMIN-only and unaffected by this."""
    revision = db.query(models.WorkflowRevision).filter(models.WorkflowRevision.id == payload.workflow_revision_id).first()
    if not revision:
        raise HTTPException(status_code=404, detail="Workflow revision not found")

    steps = (
        db.query(models.WorkflowStep)
        .filter(models.WorkflowStep.revision_id == revision.id, models.WorkflowStep.enabled.is_(True))
        .all()
    )
    if not steps:
        raise HTTPException(status_code=400, detail="Cannot preview-run a revision with no enabled steps")
    for step in steps:
        _validate_step_fields(
            step.step_type,
            {
                "locator_strategy": step.locator_strategy,
                "locator_value": step.locator_value,
                "input_value": step.input_value,
                "expected_value": step.expected_value,
                "checkpoint_instructions": step.checkpoint_instructions,
                "is_sensitive": step.is_sensitive,
                "evidence_policy": step.evidence_policy,
                "repeat_count": step.repeat_count,
            },
        )

    run = models.WorkflowRun(
        workflow_revision_id=revision.id,
        cycle_test_result_id=None,
        status="QUEUED",
        queued_by=user.email,
        is_preview=True,
    )
    db.add(run)
    db.flush()
    _add_event(db, run.id, "RUN_QUEUED", "HUMAN")
    db.commit()
    db.refresh(run)
    _dispatch_queued_run(db, master_db, slug, run)
    return _to_run_out(db, run)


@router.get("", response_model=list[schemas.WorkflowRunOut], dependencies=[Depends(get_current_user)])
def list_runs(slug: str, status: str | None = None, db: Session = Depends(get_project_db)):
    """HYB-5: optional `status` filter — used by the recovery runbook's
    "find stuck runs" step (e.g. `?status=QUEUED` to spot a run that's
    been waiting far longer than a runner should ever take to claim)."""
    _expire_stale_leases(db)
    q = db.query(models.WorkflowRun)
    if status:
        if status not in models.WORKFLOW_RUN_STATUSES:
            raise HTTPException(status_code=400, detail=f"status must be one of {models.WORKFLOW_RUN_STATUSES}")
        q = q.filter(models.WorkflowRun.status == status)
    runs = q.order_by(models.WorkflowRun.created_at.desc()).all()
    return [_to_run_out(db, r) for r in runs]


def _build_run_detail(db: Session, run: models.WorkflowRun) -> schemas.WorkflowRunDetailOut:
    step_runs = (
        db.query(models.WorkflowStepRun)
        .filter(models.WorkflowStepRun.workflow_run_id == run.id)
        .order_by(models.WorkflowStepRun.sequence_no, models.WorkflowStepRun.id)
        .all()
    )
    step_by_id = {
        s.id: s for s in db.query(models.WorkflowStep).filter(models.WorkflowStep.id.in_([sr.workflow_step_id for sr in step_runs])).all()
    }
    step_run_outs = []
    for sr in step_runs:
        item = schemas.WorkflowStepRunOut.model_validate(sr)
        step = step_by_id.get(sr.workflow_step_id)
        if step:
            item.step_type = step.step_type
            item.step_description = step.description
            item.locator_strategy = step.locator_strategy
            item.locator_value = step.locator_value
            # input_value on a sensitive step is always a ${VAR} placeholder,
            # never the real secret (enforced at write time) -- exposing it
            # here is no different from the step-authoring list already
            # showing it unconditionally.
            item.input_value = step.input_value
            item.expected_value = step.expected_value
            item.checkpoint_instructions = step.checkpoint_instructions
        step_run_outs.append(item)

    events = (
        db.query(models.RunnerExecutionEvent)
        .filter(models.RunnerExecutionEvent.workflow_run_id == run.id)
        .order_by(models.RunnerExecutionEvent.id)
        .all()
    )

    out = schemas.WorkflowRunDetailOut.model_validate(_to_run_out(db, run))
    out.step_runs = step_run_outs
    out.events = events
    out.screenshots = db.query(models.WorkflowRunScreenshot).filter(
        models.WorkflowRunScreenshot.workflow_run_id == run.id,
    ).order_by(models.WorkflowRunScreenshot.id).all()
    return out


@router.get("/{run_id}", response_model=schemas.WorkflowRunDetailOut)
def get_run(slug: str, run_id: int, request: Request, db: Session = Depends(get_project_db), master_db: Session = Depends(get_master_db)):
    _require_user_or_runner(request, master_db)
    _expire_stale_leases(db)
    run = _get_run(db, run_id)
    return _build_run_detail(db, run)


@router.get("/{run_id}/screenshots/{screenshot_id}")
def get_run_screenshot(
    slug: str, run_id: int, screenshot_id: int,
    db: Session = Depends(get_project_db),
    storage: EvidenceStorage = Depends(get_evidence_storage),
    _user: models.User = Depends(get_current_user),
):
    _get_run(db, run_id)
    item = db.query(models.WorkflowRunScreenshot).filter(
        models.WorkflowRunScreenshot.id == screenshot_id,
        models.WorkflowRunScreenshot.workflow_run_id == run_id,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Screenshot not found")
    try:
        content = storage.get(item.object_key)
    except (FileNotFoundError, KeyError) as exc:
        raise HTTPException(status_code=404, detail="Screenshot file is missing") from exc
    return Response(content=content, media_type=item.content_type, headers={"Cache-Control": "private, max-age=300"})


@router.post("/{run_id}/cancel", response_model=schemas.WorkflowRunOut, dependencies=[Depends(get_current_user)])
def cancel_run(slug: str, run_id: int, db: Session = Depends(get_project_db), user: models.User = Depends(require_tester)):
    _expire_stale_leases(db)
    run = _get_run(db, run_id)
    if run.status in models.WORKFLOW_RUN_TERMINAL_STATUSES:
        raise HTTPException(status_code=400, detail=f"Run already ended (status: {run.status})")
    if run.status in ("QUEUED", "WAITING_FOR_TARGET", "READY"):
        # Never started -- no browser process/extension loop to cooperate
        # with, so cancel outright and revoke any pending pairing code.
        run.status = "CANCELLED"
        run.ended_at = datetime.utcnow()
        _add_event(db, run.id, "RUN_CANCELLED", "HUMAN", payload_json=f'{{"cancelled_by":"{user.email}"}}')
        db.query(models.WorkflowRunBrowserAuthorization).filter(
            models.WorkflowRunBrowserAuthorization.workflow_run_id == run.id
        ).update({"revoked": True})
    else:
        # Claimed/running/waiting -- ask the runner to stop cooperatively;
        # it observes cancel_requested and calls /complete itself. See
        # runner/src/execution/executor.ts's per-step cancel check.
        run.cancel_requested = True
    db.commit()
    db.refresh(run)
    return _to_run_out(db, run)


@router.post("/{run_id}/dispatch-failed", response_model=schemas.WorkflowRunOut)
def report_dispatched_job_failure(
    slug: str,
    run_id: int,
    payload: schemas.WorkflowRunDispatchFailureRequest,
    db: Session = Depends(get_project_db),
    _runner: models.RunnerToken = Depends(get_current_runner),
):
    """Fail an ephemeral cloud job honestly if setup/runtime crashes.

    This covers failures before Chromium is installed or before a lease can
    be claimed, which otherwise leave a QUEUED run waiting forever.
    """
    run = _get_run(db, run_id)
    if run.status in models.WORKFLOW_RUN_TERMINAL_STATUSES:
        return _to_run_out(db, run)
    run.status = "SYSTEM_ERROR"
    run.result_summary = (payload.message or "The cloud browser job did not complete")[:1000]
    run.ended_at = datetime.utcnow()
    run.lease_token = None
    run.lease_expires_at = None
    _add_event(db, run.id, "RUN_COMPLETED", "SYSTEM", payload_json='{"status":"SYSTEM_ERROR","source":"cloud_dispatch"}')
    db.commit()
    db.refresh(run)
    return _to_run_out(db, run)


# ---------- runner job-claim protocol ----------


def _claim_run_payload(db: Session, run: models.WorkflowRun, runner: models.RunnerToken):
    lease_token = uuid.uuid4().hex
    run.status = "CLAIMED"
    run.runner_id = runner.id
    run.lease_token = lease_token
    run.lease_expires_at = datetime.utcnow() + timedelta(seconds=models.LEASE_DURATION_SECONDS)
    if not run.started_at:
        run.started_at = datetime.utcnow()
    _add_event(db, run.id, "RUN_CLAIMED", "RUNNER")
    db.commit()
    db.refresh(run)

    steps = (
        db.query(models.WorkflowStep)
        .filter(models.WorkflowStep.revision_id == run.workflow_revision_id, models.WorkflowStep.enabled.is_(True))
        .order_by(models.WorkflowStep.sequence_no)
        .all()
    )

    target_base_url = None
    if run.cycle_test_result_id:
        result = db.query(models.CycleTestResult).filter(models.CycleTestResult.id == run.cycle_test_result_id).first()
        if result:
            cycle = db.query(models.TestCycle).filter(models.TestCycle.id == result.cycle_id).first()
            if cycle:
                target_base_url = cycle.target_base_url

    return {
        "claimed": True,
        "run": schemas.WorkflowRunOut.model_validate(_to_run_out(db, run)).model_dump(mode="json"),
        "steps": [schemas.WorkflowRunClaimStep.model_validate(s).model_dump(mode="json") for s in steps],
        "lease_token": lease_token,
        "target_base_url": target_base_url,
    }


@router.post("/claim")
def claim_run(
    slug: str,
    db: Session = Depends(get_project_db),
    runner: models.RunnerToken = Depends(get_current_runner),
):
    """Legacy/local mode: claim the oldest queued run."""
    _expire_stale_leases(db)
    run = (
        db.query(models.WorkflowRun)
        .filter(models.WorkflowRun.status == "QUEUED")
        .order_by(models.WorkflowRun.created_at.asc())
        .first()
    )
    if not run:
        return {"claimed": False}
    return _claim_run_payload(db, run, runner)


@router.post("/claim/{run_id}")
def claim_dispatched_run(
    slug: str,
    run_id: int,
    db: Session = Depends(get_project_db),
    runner: models.RunnerToken = Depends(get_current_runner),
):
    """On-demand mode: claim exactly the run assigned to this cloud job."""
    _expire_stale_leases(db)
    run = _get_run(db, run_id)
    if run.status != "QUEUED":
        raise HTTPException(status_code=409, detail=f"Run {run_id} is not available to claim (status: {run.status})")
    return _claim_run_payload(db, run, runner)


@router.post("/{run_id}/heartbeat", response_model=schemas.WorkflowRunOut)
@limiter.limit("120/minute")
def heartbeat(
    request: Request,
    slug: str,
    run_id: int,
    payload: schemas.RunnerHeartbeatRequest,
    db: Session = Depends(get_project_db),
    runner: models.RunnerToken = Depends(get_current_runner),
):
    _expire_stale_leases(db)
    run = _get_run(db, run_id)
    if run.status in models.WORKFLOW_RUN_LEASED_STATUSES:
        _require_lease(run, runner, payload.lease_token or "")
        run.lease_expires_at = datetime.utcnow() + timedelta(seconds=models.LEASE_DURATION_SECONDS)
        _add_event(db, run.id, "HEARTBEAT", "RUNNER")
        db.commit()
        db.refresh(run)
    elif run.status in models.WORKFLOW_RUN_PAUSED_LEASE_STATUSES:
        # HYB-4: the runner keeps heartbeating while paused at a
        # checkpoint (and while resuming) so a genuinely-dead runner is
        # still detected -- just on the much longer paused timeout.
        _require_lease(run, runner, payload.lease_token or "")
        run.lease_expires_at = datetime.utcnow() + timedelta(seconds=models.PAUSED_LEASE_DURATION_SECONDS)
        _add_event(db, run.id, "HEARTBEAT", "RUNNER")
        db.commit()
        db.refresh(run)
    return _to_run_out(db, run)


@router.post("/{run_id}/events", response_model=schemas.RunnerExecutionEventOut)
@limiter.limit("300/minute")
def post_event(
    request: Request,
    slug: str,
    run_id: int,
    payload: schemas.RunnerEventCreate,
    db: Session = Depends(get_project_db),
    runner: models.RunnerToken = Depends(get_current_runner),
):
    _expire_stale_leases(db)
    run = _get_run(db, run_id)
    _require_lease(run, runner, payload.lease_token)

    if payload.idempotency_key:
        existing = (
            db.query(models.RunnerExecutionEvent)
            .filter(
                models.RunnerExecutionEvent.workflow_run_id == run_id,
                models.RunnerExecutionEvent.idempotency_key == payload.idempotency_key,
            )
            .first()
        )
        if existing:
            return existing  # idempotent replay -- not a new row

    if payload.event_type == "CHECKPOINT_WAITING":
        run.status = "WAITING_FOR_HUMAN"
        run.checkpoint_waiting_since = datetime.utcnow()
        # HYB-4: still lease-tracked, just on the longer paused timeout
        # (see WORKFLOW_RUN_PAUSED_LEASE_STATUSES) -- the runner keeps
        # heartbeating and the same lease_token stays valid across the
        # whole pause, so a resume never needs a fresh claim.
        run.lease_expires_at = datetime.utcnow() + timedelta(seconds=models.PAUSED_LEASE_DURATION_SECONDS)

    _add_event(db, run_id, payload.event_type, payload.actor_type, payload.idempotency_key, payload.payload_json)
    db.commit()

    event = (
        db.query(models.RunnerExecutionEvent)
        .filter(models.RunnerExecutionEvent.workflow_run_id == run_id)
        .order_by(models.RunnerExecutionEvent.id.desc())
        .first()
    )
    return event


@router.post("/{run_id}/step-runs", response_model=schemas.WorkflowStepRunOut)
def start_step_run(
    slug: str,
    run_id: int,
    payload: schemas.StepRunStartRequest,
    db: Session = Depends(get_project_db),
    runner: models.RunnerToken = Depends(get_current_runner),
):
    _expire_stale_leases(db)
    run = _get_run(db, run_id)
    _require_lease(run, runner, payload.lease_token)

    step = db.query(models.WorkflowStep).filter(models.WorkflowStep.id == payload.workflow_step_id, models.WorkflowStep.revision_id == run.workflow_revision_id).first()
    if not step:
        raise HTTPException(status_code=404, detail="Workflow step not found on this run's revision")

    if run.status == "CLAIMED":
        run.status = "STARTING"
    if run.status in ("STARTING",):
        run.status = "RUNNING"

    step_run = models.WorkflowStepRun(
        workflow_run_id=run_id, workflow_step_id=step.id, sequence_no=step.sequence_no,
        attempt_number=payload.attempt_number, status="RUNNING", started_at=datetime.utcnow(),
    )
    db.add(step_run)
    _add_event(db, run_id, "STEP_STARTED", "RUNNER", payload_json=f'{{"workflow_step_id":{step.id},"sequence_no":{step.sequence_no}}}')
    db.commit()
    db.refresh(step_run)
    out = schemas.WorkflowStepRunOut.model_validate(step_run)
    out.step_type = step.step_type
    out.step_description = step.description
    return out


@router.put("/{run_id}/step-runs/{step_run_id}", response_model=schemas.WorkflowStepRunOut)
def finish_step_run(
    slug: str,
    run_id: int,
    step_run_id: int,
    payload: schemas.StepRunFinishRequest,
    db: Session = Depends(get_project_db),
    runner: models.RunnerToken = Depends(get_current_runner),
):
    _expire_stale_leases(db)
    run = _get_run(db, run_id)
    _require_lease(run, runner, payload.lease_token)

    step_run = db.query(models.WorkflowStepRun).filter(models.WorkflowStepRun.id == step_run_id, models.WorkflowStepRun.workflow_run_id == run_id).first()
    if not step_run:
        raise HTTPException(status_code=404, detail="Step run not found")
    if payload.status not in models.STEP_RUN_STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {models.STEP_RUN_STATUSES}")
    if payload.failure_category and payload.failure_category not in models.FAILURE_CATEGORIES:
        raise HTTPException(status_code=400, detail=f"failure_category must be one of {models.FAILURE_CATEGORIES}")

    step_run.status = payload.status
    step_run.outcome = payload.outcome
    step_run.failure_category = payload.failure_category
    step_run.machine_message = payload.machine_message
    step_run.locator_used_json = payload.locator_used_json
    step_run.ended_at = datetime.utcnow()

    event_type = "STEP_FAILED" if payload.status == "FAILED" else "STEP_COMPLETED"
    _add_event(db, run_id, event_type, "RUNNER", payload_json=f'{{"step_run_id":{step_run.id},"status":"{payload.status}"}}')
    db.commit()
    db.refresh(step_run)

    step = db.query(models.WorkflowStep).filter(models.WorkflowStep.id == step_run.workflow_step_id).first()
    out = schemas.WorkflowStepRunOut.model_validate(step_run)
    if step:
        out.step_type = step.step_type
        out.step_description = step.description
    return out


@router.post("/{run_id}/complete", response_model=schemas.WorkflowRunOut)
def complete_run(
    slug: str,
    run_id: int,
    payload: schemas.WorkflowRunCompleteRequest,
    db: Session = Depends(get_project_db),
    runner: models.RunnerToken = Depends(get_current_runner),
):
    _expire_stale_leases(db)
    run = _get_run(db, run_id)
    _require_lease(run, runner, payload.lease_token)

    # RUNNER_LOST is included here (not just as the lease-sweep's own
    # verdict) so a runner that's still connected but just lost its own
    # Chromium session while paused at a checkpoint can self-report
    # honestly rather than silently going quiet until the lease sweep
    # catches it (see docs/hybrid/SESSION_HANDOFF.md's HYB-4 lost-browser
    # requirement).
    allowed_terminal = {"PASSED", "FAILED", "BLOCKED", "SYSTEM_ERROR", "CANCELLED", "RUNNER_LOST"}
    if payload.status not in allowed_terminal:
        raise HTTPException(status_code=400, detail=f"status must be one of {sorted(allowed_terminal)}")

    run.status = payload.status
    run.ended_at = datetime.utcnow()
    run.result_summary = payload.result_summary
    run.lease_token = None
    run.lease_expires_at = None
    _add_event(db, run_id, "RUN_COMPLETED", "RUNNER", payload_json=f'{{"status":"{payload.status}"}}')
    db.commit()
    db.refresh(run)
    return _to_run_out(db, run)


# ---------- evidence (reuses the real EvidenceStorage abstraction) ----------


@router.post("/{run_id}/evidence", response_model=schemas.EvidenceItemOut)
async def upload_run_evidence(
    slug: str,
    run_id: int,
    lease_token: str,
    step_run_id: int | None = None,
    file: UploadFile = File(...),
    db: Session = Depends(get_project_db),
    master_db: Session = Depends(get_master_db),
    storage: EvidenceStorage = Depends(get_evidence_storage),
    runner: models.RunnerToken = Depends(get_current_runner),
):
    """Deliberately requires cycle_test_result_id -- preserves
    EvidenceItem's existing NOT NULL cycle_id/cycle_test_result_id
    invariant unchanged rather than weakening it for standalone runs.
    A run not linked to a cycle result cannot upload evidence through
    this endpoint (documented gap, see docs/hybrid/
    HYB-1-GAP-ANALYSIS-REFRESH.md decision 2)."""
    _expire_stale_leases(db)
    run = _get_run(db, run_id)
    _require_lease(run, runner, lease_token)
    if not run.cycle_test_result_id:
        raise HTTPException(
            status_code=400,
            detail="This run has no cycle_test_result_id — screenshot evidence requires the run to be linked to a Track A cycle result.",
        )
    result = db.query(models.CycleTestResult).filter(models.CycleTestResult.id == run.cycle_test_result_id).first()
    if not result:
        raise HTTPException(status_code=404, detail="Linked cycle result no longer exists")
    cycle = db.query(models.TestCycle).filter(models.TestCycle.id == result.cycle_id).first()
    if cycle and cycle.status == "LOCKED":
        raise HTTPException(status_code=400, detail="Cycle is LOCKED — evidence cannot be added. An admin must /reopen it first.")

    upload_started = time.perf_counter()
    content = await file.read()
    if len(content) > MAX_EVIDENCE_SIZE_BYTES:
        raise HTTPException(status_code=400, detail=f"Evidence file exceeds the {MAX_EVIDENCE_SIZE_BYTES // (1024*1024)}MB limit")
    sniffed = sniff_image(content)
    if not sniffed:
        raise HTTPException(status_code=400, detail="File is not a recognized image (PNG/JPEG/GIF/WEBP signature check failed)")
    content_type, ext = sniffed
    sha256 = hashlib.sha256(content).hexdigest()

    project = master_db.query(models.Project).filter(models.Project.slug == slug).first()
    status_before = quota_status(project, db)
    if status_before["used_bytes"] + len(content) > status_before["quota_bytes"]:
        raise HTTPException(status_code=400, detail="Uploading this file would exceed the project's storage quota")

    existing = (
        db.query(models.EvidenceItem)
        .filter(
            models.EvidenceItem.cycle_test_result_id == result.id,
            models.EvidenceItem.original_sha256 == sha256,
            models.EvidenceItem.status == "ACTIVE",
        )
        .first()
    )
    if existing:
        return existing

    object_key = f"evidence/{slug}/{result.id}/{uuid.uuid4().hex}.{ext}"
    try:
        storage.put(object_key, content, content_type)
    except Exception as exc:
        logger.error("Runner evidence storage write failed for key %s: %s", object_key, exc)
        raise HTTPException(status_code=502, detail="Could not store the evidence file — nothing was saved, safe to retry") from exc

    item = models.EvidenceItem(
        cycle_id=result.cycle_id,
        cycle_test_result_id=result.id,
        evidence_type="SCREENSHOT",
        object_key=object_key,
        original_filename=file.filename or "runner-screenshot.png",
        original_content_type=content_type,
        original_size_bytes=len(content),
        original_sha256=sha256,
        captured_by=f"runner:{runner.label}",
        evidence_source="RUNNER",
        workflow_run_id=run.id,
        workflow_step_run_id=step_run_id,
        upload_duration_ms=round((time.perf_counter() - upload_started) * 1000),
    )
    try:
        db.add(item)
        db.commit()
        db.refresh(item)
    except Exception as exc:
        db.rollback()
        try:
            storage.delete(object_key)
        except Exception as cleanup_exc:
            logger.error("ORPHANED EVIDENCE OBJECT (runner upload, failed DB insert, cleanup also failed): %s / %s", object_key, cleanup_exc)
        raise HTTPException(status_code=500, detail="The evidence file could not be recorded — retry the upload.") from exc

    _add_event(db, run_id, "STEP_COMPLETED", "RUNNER", payload_json=f'{{"evidence_id":{item.id},"kind":"screenshot"}}')
    db.commit()
    return item


# ---------- HYB-4: manual checkpoints (human decision + resume) ----------


def _get_checkpoint_step(db: Session, run: models.WorkflowRun, workflow_step_id: int) -> models.WorkflowStep:
    step = (
        db.query(models.WorkflowStep)
        .filter(models.WorkflowStep.id == workflow_step_id, models.WorkflowStep.revision_id == run.workflow_revision_id)
        .first()
    )
    if not step:
        raise HTTPException(status_code=404, detail="Workflow step not found on this run's revision")
    if step.step_type != "MANUAL_CHECKPOINT":
        raise HTTPException(status_code=400, detail="This step is not a MANUAL_CHECKPOINT")
    return step


def _decisions_for(db: Session, run_id: int, workflow_step_id: int) -> list[models.WorkflowCheckpointDecision]:
    return (
        db.query(models.WorkflowCheckpointDecision)
        .filter(
            models.WorkflowCheckpointDecision.workflow_run_id == run_id,
            models.WorkflowCheckpointDecision.workflow_step_id == workflow_step_id,
        )
        .order_by(models.WorkflowCheckpointDecision.decision_revision_no)
        .all()
    )


@router.get("/{run_id}/checkpoint", response_model=schemas.CheckpointContextOut)
def get_checkpoint_context(
    slug: str,
    run_id: int,
    workflow_step_id: int,
    db: Session = Depends(get_project_db),
    _user: models.User = Depends(get_current_user),
):
    """Everything the human-checkpoint review UI needs in one call --
    linked Track A test case(s) at the exact revision snapshot, the
    workflow revision, prior automated step results, machine assertions
    (the step-run history already carries these), and this checkpoint's
    own decision history. Reuses WorkflowRunDetailOut rather than a
    parallel shape."""
    _expire_stale_leases(db)
    run = _get_run(db, run_id)
    step = _get_checkpoint_step(db, run, workflow_step_id)

    revision = db.query(models.WorkflowRevision).filter(models.WorkflowRevision.id == run.workflow_revision_id).first()
    workflow_name = None
    if revision:
        wf = db.query(models.WorkflowDefinition).filter(models.WorkflowDefinition.id == revision.workflow_id).first()
        workflow_name = wf.name if wf else None

    links = (
        db.query(models.WorkflowTestCaseLink)
        .filter(models.WorkflowTestCaseLink.workflow_revision_id == run.workflow_revision_id)
        .all()
    )
    case_by_id = {c.id: c for c in db.query(models.TestCase).filter(models.TestCase.id.in_([l.test_case_id for l in links])).all()}
    link_outs = []
    for l in links:
        out = schemas.WorkflowTestCaseLinkOut.model_validate(l)
        case = case_by_id.get(l.test_case_id)
        if case:
            out.checkpoint_code = case.checkpoint_code
            out.case_title = case.title
        link_outs.append(out)

    elapsed = None
    if run.checkpoint_waiting_since:
        elapsed = (datetime.utcnow() - run.checkpoint_waiting_since).total_seconds()

    cycle_id = None
    if run.cycle_test_result_id:
        result = db.query(models.CycleTestResult).filter(models.CycleTestResult.id == run.cycle_test_result_id).first()
        if result:
            cycle_id = result.cycle_id

    return schemas.CheckpointContextOut(
        run=_build_run_detail(db, run),
        workflow_step_id=step.id,
        step_description=step.description,
        checkpoint_instructions=step.checkpoint_instructions,
        expected_value=step.expected_value,
        workflow_name=workflow_name,
        workflow_revision_label=revision.revision_label if revision else None,
        cycle_id=cycle_id,
        linked_test_cases=link_outs,
        decisions=_decisions_for(db, run_id, workflow_step_id),
        checkpoint_waiting_since=run.checkpoint_waiting_since,
        elapsed_waiting_seconds=elapsed,
    )


@router.get("/{run_id}/checkpoint-decisions", response_model=list[schemas.WorkflowCheckpointDecisionOut], dependencies=[Depends(get_current_user)])
def list_checkpoint_decisions(slug: str, run_id: int, workflow_step_id: int | None = None, db: Session = Depends(get_project_db)):
    _get_run(db, run_id)
    q = db.query(models.WorkflowCheckpointDecision).filter(models.WorkflowCheckpointDecision.workflow_run_id == run_id)
    if workflow_step_id is not None:
        q = q.filter(models.WorkflowCheckpointDecision.workflow_step_id == workflow_step_id)
    return q.order_by(models.WorkflowCheckpointDecision.id).all()


@router.post("/{run_id}/checkpoint-decision", response_model=schemas.WorkflowCheckpointDecisionOut)
def submit_checkpoint_decision(
    slug: str,
    run_id: int,
    payload: schemas.WorkflowCheckpointDecisionCreate,
    db: Session = Depends(get_project_db),
    user: models.User = Depends(require_tester),
):
    """The human-decision half of HYB-4's resume protocol -- user-session
    auth only, never a runner token or a trusted client-supplied
    identity (decided_by_* is always taken from `user`, server-derived).

    Decision-conflict protection: the same atomic transaction that
    inserts the decision row also flips run.status away from
    WAITING_FOR_HUMAN. A second, racing decision request finds
    run.status already moved on and is rejected with 409 -- "first
    commit wins", the same pattern already used for the evidence-upload
    quota race. SQLite serializes writer commits, so whichever request's
    commit lands first deterministically wins; there is no window where
    both could succeed.

    Idempotency: a retried POST (double-click, network retry) with the
    same idempotency_key returns the original decision instead of
    erroring or duplicating -- checked before the WAITING_FOR_HUMAN gate
    so a legitimate retry succeeds even after the run has already moved
    on because of that exact request's own earlier, successfully-
    committed attempt.
    """
    _expire_stale_leases(db)
    run = _get_run(db, run_id)
    step = _get_checkpoint_step(db, run, payload.workflow_step_id)

    if payload.idempotency_key:
        existing = (
            db.query(models.WorkflowCheckpointDecision)
            .filter(
                models.WorkflowCheckpointDecision.workflow_run_id == run_id,
                models.WorkflowCheckpointDecision.workflow_step_id == step.id,
                models.WorkflowCheckpointDecision.idempotency_key == payload.idempotency_key,
            )
            .first()
        )
        if existing:
            return existing

    if run.status != "WAITING_FOR_HUMAN":
        raise HTTPException(
            status_code=409,
            detail=f"This run is not currently waiting for a human decision (status: {run.status}) — "
            "the checkpoint may already have been decided by someone else, or the run has ended.",
        )

    if payload.status not in models.CHECKPOINT_DECISION_STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {models.CHECKPOINT_DECISION_STATUSES}")
    if payload.status == "FAIL" and not (payload.actual_result_md or "").strip():
        raise HTTPException(status_code=400, detail="FAIL requires an actual result")
    if payload.status == "BLOCKED" and not (payload.reason or "").strip():
        raise HTTPException(status_code=400, detail="BLOCKED requires a reason")
    if payload.status == "NOT_APPLICABLE" and not (payload.reason or "").strip():
        raise HTTPException(status_code=400, detail="NOT_APPLICABLE requires a reason")

    cycle = None
    result = None
    if run.cycle_test_result_id:
        result = db.query(models.CycleTestResult).filter(models.CycleTestResult.id == run.cycle_test_result_id).first()
        if result:
            cycle = db.query(models.TestCycle).filter(models.TestCycle.id == result.cycle_id).first()
        if cycle and cycle.status == "LOCKED":
            raise HTTPException(status_code=400, detail="Cycle is LOCKED — checkpoint decisions cannot be recorded. An admin must /reopen it first.")
        if payload.status == "PASS" and cycle and cycle.require_evidence_for_pass:
            has_evidence = (
                db.query(models.EvidenceItem)
                .filter(models.EvidenceItem.cycle_test_result_id == result.id, models.EvidenceItem.status == "ACTIVE")
                .first()
            )
            if not has_evidence:
                raise HTTPException(
                    status_code=400,
                    detail="PASS requires at least one evidence item (this cycle's require_evidence_for_pass is enabled)",
                )

    prior = _decisions_for(db, run_id, step.id)
    next_revision_no = (prior[-1].decision_revision_no + 1) if prior else 1
    resume_authorized = payload.status == "PASS"

    checkpoint_step_run = (
        db.query(models.WorkflowStepRun)
        .filter(models.WorkflowStepRun.workflow_run_id == run_id, models.WorkflowStepRun.workflow_step_id == step.id)
        .order_by(models.WorkflowStepRun.id.desc())
        .first()
    )

    decision = models.WorkflowCheckpointDecision(
        workflow_run_id=run_id,
        workflow_step_id=step.id,
        workflow_step_run_id=checkpoint_step_run.id if checkpoint_step_run else None,
        decision_revision_no=next_revision_no,
        status=payload.status,
        actual_result_md=payload.actual_result_md,
        reason=payload.reason,
        decided_by_user_id=user.id,
        decided_by_email=user.email,
        source="HUMAN",
        resume_authorized=resume_authorized,
        review_status="UNREVIEWED" if payload.status == "NOT_APPLICABLE" else None,
        idempotency_key=payload.idempotency_key,
    )
    db.add(decision)
    db.flush()

    # Link any evidence the reviewer attached while deciding. Server-side
    # only, and scoped to this exact cycle_test_result_id so a client
    # can't attach evidence belonging to an unrelated result.
    if payload.evidence_ids and run.cycle_test_result_id:
        db.query(models.EvidenceItem).filter(
            models.EvidenceItem.id.in_(payload.evidence_ids),
            models.EvidenceItem.cycle_test_result_id == run.cycle_test_result_id,
        ).update({models.EvidenceItem.checkpoint_decision_id: decision.id}, synchronize_session=False)

    # Finalize the checkpoint's own step-run row now -- independent of
    # whether the runner ever reconnects to observe it. STEP_RUN_STATUSES
    # has no BLOCKED/NOT_APPLICABLE state of its own (it's shared with
    # automated step execution); PASSED/FAILED is enough to be honest
    # here since the real distinction lives on the decision row itself.
    if checkpoint_step_run:
        checkpoint_step_run.status = "PASSED" if payload.status == "PASS" else "FAILED"
        checkpoint_step_run.outcome = f"Human checkpoint decision: {payload.status}"
        checkpoint_step_run.ended_at = datetime.utcnow()

    if resume_authorized:
        run.status = "RESUMING"
        # lease_token/lease_expires_at deliberately left as-is -- the same
        # runner, same lease, same browser session picks this up on its
        # next poll via POST /checkpoint-resume.
    else:
        run.status = "BLOCKED" if payload.status == "BLOCKED" else ("NOT_APPLICABLE" if payload.status == "NOT_APPLICABLE" else "FAILED")
        run.ended_at = datetime.utcnow()
        run.lease_token = None
        run.lease_expires_at = None
    run.checkpoint_waiting_since = None

    _add_event(
        db, run_id, "CHECKPOINT_DECIDED", "HUMAN",
        payload_json=f'{{"decision_id":{decision.id},"status":"{payload.status}","workflow_step_id":{step.id}}}',
    )
    db.commit()
    db.refresh(decision)
    return decision


@router.post("/{run_id}/checkpoint-decisions/{decision_id}/review", response_model=schemas.WorkflowCheckpointDecisionOut)
def review_checkpoint_decision(
    slug: str,
    run_id: int,
    decision_id: int,
    payload: schemas.CheckpointDecisionReviewRequest,
    db: Session = Depends(get_project_db),
    user: models.User = Depends(require_admin),
):
    """Admin approval for NOT_APPLICABLE checkpoint decisions -- mirrors
    routers/cycle_results.py::review_result's existing Track A policy
    rather than inventing a second one."""
    decision = (
        db.query(models.WorkflowCheckpointDecision)
        .filter(models.WorkflowCheckpointDecision.id == decision_id, models.WorkflowCheckpointDecision.workflow_run_id == run_id)
        .first()
    )
    if not decision:
        raise HTTPException(status_code=404, detail="Checkpoint decision not found")
    if decision.status != "NOT_APPLICABLE":
        raise HTTPException(status_code=400, detail="Only a NOT_APPLICABLE decision can be reviewed")
    if payload.review_status not in ("ACCEPTED", "CHANGES_REQUESTED"):
        raise HTTPException(status_code=400, detail="review_status must be ACCEPTED or CHANGES_REQUESTED")

    decision.review_status = payload.review_status
    decision.reviewed_by = user.email
    decision.reviewed_at = datetime.utcnow()
    db.commit()
    db.refresh(decision)
    return decision


@router.post("/{run_id}/checkpoint-resume", response_model=schemas.CheckpointResumeOut)
def resume_after_checkpoint(
    slug: str,
    run_id: int,
    payload: schemas.CheckpointResumeRequest,
    db: Session = Depends(get_project_db),
    runner: models.RunnerToken = Depends(get_current_runner),
):
    """The runner calls this after observing (via heartbeat/poll) that
    its paused run moved to RESUMING. Validates the response belongs to
    the correct run/step/checkpoint/decision before honoring it (a stale
    or mismatched request never resumes anything), and is idempotent
    against a duplicate resume call from the same still-connected runner.
    A *different* runner process (no live browser, no knowledge of this
    lease_token) cannot call this at all -- _require_lease rejects it,
    the same as every other runner-authenticated action -- so a resume
    can never be fabricated by a fresh process that doesn't actually
    hold the original browser session."""
    _expire_stale_leases(db)
    run = _get_run(db, run_id)
    step = _get_checkpoint_step(db, run, payload.workflow_step_id)

    if run.status == "RUNNING":
        # Idempotent replay of an already-completed resume from the same
        # (lease-verified) runner -- not an error, not a re-trigger.
        _require_lease(run, runner, payload.lease_token)
    elif run.status != "RESUMING":
        raise HTTPException(
            status_code=409,
            detail=f"This run is not in RESUMING state (status: {run.status}) — nothing to resume.",
        )
    else:
        _require_lease(run, runner, payload.lease_token)

    latest = _decisions_for(db, run_id, step.id)
    decision = latest[-1] if latest else None
    if not decision or not decision.resume_authorized:
        raise HTTPException(status_code=409, detail="No PASS decision authorizes resuming this checkpoint")

    if run.status == "RESUMING":
        run.status = "RUNNING"
        run.lease_expires_at = datetime.utcnow() + timedelta(seconds=models.LEASE_DURATION_SECONDS)
        _add_event(
            db, run_id, "RUN_RESUMED", "RUNNER",
            payload_json=f'{{"workflow_step_id":{step.id},"decision_id":{decision.id}}}',
        )
        db.commit()
        db.refresh(run)

    remaining_steps = (
        db.query(models.WorkflowStep)
        .filter(
            models.WorkflowStep.revision_id == run.workflow_revision_id,
            models.WorkflowStep.enabled.is_(True),
            models.WorkflowStep.sequence_no > step.sequence_no,
        )
        .order_by(models.WorkflowStep.sequence_no)
        .all()
    )

    return schemas.CheckpointResumeOut(
        run=schemas.WorkflowRunOut.model_validate(_to_run_out(db, run)),
        steps=[schemas.WorkflowRunClaimStep.model_validate(s) for s in remaining_steps],
        decision=schemas.WorkflowCheckpointDecisionOut.model_validate(decision),
    )
