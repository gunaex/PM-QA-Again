"""HYB-5: timing derivation for hybrid workflow runs.

Every duration here is *derived* from timestamps that already exist on
`WorkflowRun` / `WorkflowStepRun` / `RunnerExecutionEvent` /
`WorkflowCheckpointDecision` — HYB-2/HYB-4 already capture the raw
`created_at`/`started_at`/`ended_at`/`decided_at` moments this module
reads. The one genuinely new measurement is
`EvidenceItem.upload_duration_ms`, timing the upload endpoint's own
server-side read+hash+store work (not network transfer time — this
process never sees the client's upload start).

Historical runs are never overwritten: this module only ever reads.
Nothing here mutates a run/step/event/decision row.

Four buckets, kept distinct per the HYB-5 spec rather than merged into
one "duration":
  - `application`: time the workflow's own step assertions/actions took
    (WorkflowStepRun started_at -> ended_at).
  - `queue_and_runner`: time between a run being queued and a runner
    actually claiming/starting it (queue_delay, browser_startup).
  - `manual_waiting`: time a human held up a paused run (checkpoint
    waiting duration, human decision time, resume delay).
  - `infrastructure`: everything else attributable to the platform
    itself (evidence upload duration).
"""
import json
from datetime import datetime

from sqlalchemy.orm import Session

from . import models


def _seconds(a: datetime | None, b: datetime | None) -> float | None:
    if a is None or b is None:
        return None
    return round((b - a).total_seconds(), 3)


def _step_id_from_payload(payload_json: str | None) -> int | None:
    if not payload_json:
        return None
    try:
        data = json.loads(payload_json)
    except (ValueError, TypeError):
        return None
    if "workflow_step_id" in data:
        return data["workflow_step_id"]
    if "step_id" in data:
        return data["step_id"]
    payload = data.get("payload")
    if isinstance(payload, dict):
        return payload.get("step_id")
    return None


def _events_by_type(db: Session, run_id: int) -> dict[str, list[models.RunnerExecutionEvent]]:
    events = (
        db.query(models.RunnerExecutionEvent)
        .filter(models.RunnerExecutionEvent.workflow_run_id == run_id)
        .order_by(models.RunnerExecutionEvent.id)
        .all()
    )
    by_type: dict[str, list[models.RunnerExecutionEvent]] = {}
    for e in events:
        by_type.setdefault(e.event_type, []).append(e)
    return by_type


def checkpoint_timings(db: Session, run_id: int) -> list[dict]:
    """One entry per checkpoint occurrence (a run may pause more than
    once across different MANUAL_CHECKPOINT steps). Matches each
    CHECKPOINT_WAITING event to the CHECKPOINT_DECIDED/RUN_RESUMED events
    carrying the same workflow_step_id, in chronological order — the
    same (run_id, step_id) pair is never decided twice in the normal
    flow (HYB-4's decision-conflict CAS), so first-available-match is
    sufficient here."""
    by_type = _events_by_type(db, run_id)
    waiting = by_type.get("CHECKPOINT_WAITING", [])
    decided = by_type.get("CHECKPOINT_DECIDED", [])
    resumed = by_type.get("RUN_RESUMED", [])

    used_decided: set[int] = set()
    used_resumed: set[int] = set()
    out = []
    for w in waiting:
        step_id = _step_id_from_payload(w.payload_json)
        decided_evt = next(
            (d for d in decided if d.id not in used_decided and _step_id_from_payload(d.payload_json) == step_id and d.id > w.id),
            None,
        )
        if decided_evt:
            used_decided.add(decided_evt.id)
        resumed_evt = next(
            (r for r in resumed if r.id not in used_resumed and _step_id_from_payload(r.payload_json) == step_id and (decided_evt is None or r.id > decided_evt.id)),
            None,
        )
        if resumed_evt:
            used_resumed.add(resumed_evt.id)

        entered_at = w.created_at
        decided_at = decided_evt.created_at if decided_evt else None
        resumed_at = resumed_evt.created_at if resumed_evt else None
        out.append(
            {
                "workflow_step_id": step_id,
                "checkpoint_entered_at": entered_at,
                "decided_at": decided_at,
                "resumed_at": resumed_at,
                # "manual waiting time" bucket — how long a human held up
                # this run, start to finish, regardless of what happens after.
                "checkpoint_waiting_duration_seconds": _seconds(entered_at, decided_at),
                # a sub-component of the above: from the human's own
                # decided_at back to when the checkpoint appeared —
                # identical to waiting_duration today (this app has no
                # separate "reviewer opened the panel" timestamp yet), kept
                # as its own field so a future "time to first view" capture
                # can populate it without a schema change downstream.
                "human_decision_time_seconds": _seconds(entered_at, decided_at),
                # queue_and_runner-adjacent: how long after a PASS decision
                # before the runner's own poll loop actually resumed —
                # runner poll-interval + heartbeat latency, not human time.
                "resume_delay_seconds": _seconds(decided_at, resumed_at),
            }
        )
    return out


def run_timing(db: Session, run: models.WorkflowRun) -> dict:
    by_type = _events_by_type(db, run.id)
    claimed = by_type.get("RUN_CLAIMED", [])
    step_started = by_type.get("STEP_STARTED", [])

    queue_delay_seconds = _seconds(run.created_at, claimed[0].created_at) if claimed else None
    browser_startup_seconds = (
        _seconds(claimed[0].created_at, step_started[0].created_at) if claimed and step_started else None
    )

    step_runs = (
        db.query(models.WorkflowStepRun)
        .filter(models.WorkflowStepRun.workflow_run_id == run.id)
        .order_by(models.WorkflowStepRun.sequence_no, models.WorkflowStepRun.attempt_number)
        .all()
    )
    steps = []
    by_step_id: dict[int, list[models.WorkflowStepRun]] = {}
    for sr in step_runs:
        by_step_id.setdefault(sr.workflow_step_id, []).append(sr)
    for sr in step_runs:
        attempts_for_step = by_step_id[sr.workflow_step_id]
        steps.append(
            {
                "workflow_step_run_id": sr.id,
                "workflow_step_id": sr.workflow_step_id,
                "sequence_no": sr.sequence_no,
                "attempt_number": sr.attempt_number,
                "is_retry": sr.attempt_number > 1,
                "status": sr.status,
                "failure_category": sr.failure_category,
                "started_at": sr.started_at,
                "ended_at": sr.ended_at,
                "duration_seconds": _seconds(sr.started_at, sr.ended_at),
                "attempt_count_for_step": len(attempts_for_step),
            }
        )

    checkpoints = checkpoint_timings(db, run.id)
    total_manual_waiting_seconds = sum(
        c["checkpoint_waiting_duration_seconds"] for c in checkpoints if c["checkpoint_waiting_duration_seconds"] is not None
    ) or None
    total_application_seconds = sum(s["duration_seconds"] for s in steps if s["duration_seconds"] is not None) or None

    evidence_items = (
        db.query(models.EvidenceItem)
        .filter(models.EvidenceItem.workflow_run_id == run.id)
        .all()
    )

    return {
        "run_id": run.id,
        "status": run.status,
        "run_created_at": run.created_at,
        "run_started_at": run.started_at,
        "run_ended_at": run.ended_at,
        "queue_delay_seconds": queue_delay_seconds,
        "runner_claim_delay_seconds": queue_delay_seconds,
        "browser_startup_seconds": browser_startup_seconds,
        "total_run_duration_seconds": _seconds(run.created_at, run.ended_at),
        "execution_duration_seconds": _seconds(run.started_at, run.ended_at),
        "total_application_step_seconds": total_application_seconds,
        "total_manual_waiting_seconds": total_manual_waiting_seconds,
        "steps": steps,
        "checkpoints": checkpoints,
        "evidence_uploads": [
            {
                "evidence_id": e.id,
                "workflow_step_run_id": e.workflow_step_run_id,
                "captured_at": e.captured_at,
                "upload_duration_ms": e.upload_duration_ms,
            }
            for e in evidence_items
        ],
    }


def step_duration_trend(db: Session, workflow_id: int, step_description: str, limit: int = 50) -> list[dict]:
    """Trend of one logical step's duration across every run of the
    given workflow, oldest-run-first, most recent `limit` runs. Matched
    by (workflow_id, exact step description) — there is no stable
    logical-step key across revisions yet (each publish creates new
    WorkflowStep rows), so this is a documented approximation: a step
    renamed across revisions will not chain into the same trend line.
    Denominator: only WorkflowStepRun rows whose step matches and whose
    run reached a real terminal status are counted (in-flight/queued
    runs contribute no data point yet)."""
    rows = (
        db.query(models.WorkflowStepRun, models.WorkflowRun, models.WorkflowStep)
        .join(models.WorkflowRun, models.WorkflowRun.id == models.WorkflowStepRun.workflow_run_id)
        .join(models.WorkflowStep, models.WorkflowStep.id == models.WorkflowStepRun.workflow_step_id)
        .join(models.WorkflowRevision, models.WorkflowRevision.id == models.WorkflowStep.revision_id)
        .filter(
            models.WorkflowRevision.workflow_id == workflow_id,
            models.WorkflowStep.description == step_description,
            models.WorkflowRun.status.in_(models.WORKFLOW_RUN_TERMINAL_STATUSES),
        )
        .order_by(models.WorkflowRun.created_at.asc())
        .limit(limit)
        .all()
    )
    return [
        {
            "run_id": run.id,
            "run_created_at": run.created_at,
            "attempt_number": step_run.attempt_number,
            "status": step_run.status,
            "duration_seconds": _seconds(step_run.started_at, step_run.ended_at),
        }
        for step_run, run, step in rows
    ]


def run_duration_trend(db: Session, workflow_id: int, limit: int = 50) -> list[dict]:
    """Total run duration across every run of a workflow's revisions,
    oldest first. Only terminal runs are counted (denominator: runs that
    actually finished, one way or another)."""
    rows = (
        db.query(models.WorkflowRun)
        .join(models.WorkflowRevision, models.WorkflowRevision.id == models.WorkflowRun.workflow_revision_id)
        .filter(
            models.WorkflowRevision.workflow_id == workflow_id,
            models.WorkflowRun.status.in_(models.WORKFLOW_RUN_TERMINAL_STATUSES),
        )
        .order_by(models.WorkflowRun.created_at.asc())
        .limit(limit)
        .all()
    )
    return [
        {
            "run_id": r.id,
            "workflow_revision_id": r.workflow_revision_id,
            "status": r.status,
            "run_created_at": r.created_at,
            "total_run_duration_seconds": _seconds(r.created_at, r.ended_at),
            "execution_duration_seconds": _seconds(r.started_at, r.ended_at),
        }
        for r in rows
    ]
