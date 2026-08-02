"""HYB-5: hybrid dashboard/report aggregates — Track B (workflow runs)
only. Never touches Track A's own dashboard.py/metrics.py/reports.py
formulas; every function here is additive and reads workflow_run*/
workflow_checkpoint_decisions/runner_execution_events/runner_tokens.

Every aggregate below states its denominator in its own docstring or
return shape per the HYB-5 spec's "clearly labeled denominators"
requirement. All queries use SQLAlchemy `func.count`/`group_by` (no
N+1 per-row follow-up queries) and stay off unbounded payloads —
list-style results are capped or naturally small (one row per
workflow/category/runner, not per run).
"""
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from . import models


def run_status_counts(db: Session) -> dict[str, int]:
    """Denominator: every WorkflowRun row that exists in this project,
    regardless of age. One GROUP BY, not one query per status."""
    counts = {s: 0 for s in models.WORKFLOW_RUN_STATUSES}
    for status, n in db.query(models.WorkflowRun.status, func.count(models.WorkflowRun.id)).group_by(models.WorkflowRun.status).all():
        counts[status] = n
    return counts


def step_outcome_counts(db: Session) -> dict[str, int]:
    """Machine step outcomes. Denominator: every WorkflowStepRun row
    (every attempted automated step across every run), not just the
    latest attempt per step."""
    counts = {s: 0 for s in models.STEP_RUN_STATUSES}
    for status, n in db.query(models.WorkflowStepRun.status, func.count(models.WorkflowStepRun.id)).group_by(models.WorkflowStepRun.status).all():
        counts[status] = n
    return counts


def checkpoint_decision_counts(db: Session) -> dict[str, int]:
    """Human checkpoint decisions. Denominator: every
    WorkflowCheckpointDecision row (one per actual human decision,
    append-only — a re-decided checkpoint counts each decision, not
    just the latest)."""
    counts = {s: 0 for s in models.CHECKPOINT_DECISION_STATUSES}
    for status, n in (
        db.query(models.WorkflowCheckpointDecision.status, func.count(models.WorkflowCheckpointDecision.id))
        .group_by(models.WorkflowCheckpointDecision.status)
        .all()
    ):
        counts[status] = n
    return counts


def provenance_summary(db: Session) -> dict:
    """Machine-vs-human split, kept structurally distinct rather than
    merged into one number: automated step outcomes are never counted
    as a "decision", and human checkpoint decisions are never counted
    as a "step outcome" — the two tables have no overlap by
    construction (WorkflowStepRun rows are always RUNNER-driven;
    WorkflowCheckpointDecision rows are always source=HUMAN)."""
    return {
        "machine_step_outcomes": step_outcome_counts(db),
        "human_checkpoint_decisions": checkpoint_decision_counts(db),
        "human_fail_is_terminal_note": (
            "A HUMAN FAIL decision ends the run FAILED in the same transaction "
            "that flips run.status away from WAITING_FOR_HUMAN; no later "
            "automated event can reopen or overwrite it (see workflow_runs.py's "
            "submit_checkpoint_decision decision-conflict CAS)."
        ),
    }


def locator_failure_frequency(db: Session, limit: int = 20) -> list[dict]:
    """Denominator: WorkflowStepRun rows with failure_category ==
    LOCATOR_NOT_FOUND or LOCATOR_AMBIGUOUS, grouped by workflow_step_id.
    Only steps that have actually failed at least once appear; a step
    with zero locator failures is absent, not zero-padded, to keep the
    payload bounded."""
    rows = (
        db.query(
            models.WorkflowStepRun.workflow_step_id,
            models.WorkflowStep.description,
            models.WorkflowStepRun.failure_category,
            func.count(models.WorkflowStepRun.id),
        )
        .join(models.WorkflowStep, models.WorkflowStep.id == models.WorkflowStepRun.workflow_step_id)
        .filter(models.WorkflowStepRun.failure_category.in_(["LOCATOR_NOT_FOUND", "LOCATOR_AMBIGUOUS"]))
        .group_by(models.WorkflowStepRun.workflow_step_id, models.WorkflowStep.description, models.WorkflowStepRun.failure_category)
        .order_by(func.count(models.WorkflowStepRun.id).desc())
        .limit(limit)
        .all()
    )
    return [
        {"workflow_step_id": step_id, "step_description": desc, "failure_category": cat, "failure_count": n}
        for step_id, desc, cat, n in rows
    ]


def failure_category_breakdown(db: Session) -> dict[str, int]:
    """Denominator: every WorkflowStepRun row with status == FAILED. A
    step_run with a null failure_category (should not normally happen,
    but a runner bug or a cancelled-mid-step row could leave one) is
    bucketed under "UNCATEGORIZED" rather than silently dropped."""
    counts = {c: 0 for c in models.FAILURE_CATEGORIES}
    counts["UNCATEGORIZED"] = 0
    rows = (
        db.query(models.WorkflowStepRun.failure_category, func.count(models.WorkflowStepRun.id))
        .filter(models.WorkflowStepRun.status == "FAILED")
        .group_by(models.WorkflowStepRun.failure_category)
        .all()
    )
    for cat, n in rows:
        counts[cat or "UNCATEGORIZED"] = counts.get(cat or "UNCATEGORIZED", 0) + n
    return counts


def runner_reliability(db: Session, master_db) -> list[dict]:
    """Per-runner reliability, joined against the master-DB
    runner_tokens table (runner identity lives cross-DB — see
    WorkflowRun.runner_id's own comment). Denominator per runner: every
    WorkflowRun row ever claimed by that runner_id (runs never claimed
    by anyone are excluded — nothing to attribute them to)."""
    rows = (
        db.query(models.WorkflowRun.runner_id, models.WorkflowRun.status, func.count(models.WorkflowRun.id))
        .filter(models.WorkflowRun.runner_id.isnot(None))
        .group_by(models.WorkflowRun.runner_id, models.WorkflowRun.status)
        .all()
    )
    by_runner: dict[int, dict[str, int]] = {}
    for runner_id, status, n in rows:
        by_runner.setdefault(runner_id, {}).setdefault(status, 0)
        by_runner[runner_id][status] += n

    tokens = {
        t.id: t
        for t in master_db.query(models.RunnerToken).filter(models.RunnerToken.id.in_(by_runner.keys())).all()
    } if by_runner else {}

    out = []
    for runner_id, status_counts in by_runner.items():
        total = sum(status_counts.values())
        lost = status_counts.get("RUNNER_LOST", 0)
        passed = status_counts.get("PASSED", 0)
        token = tokens.get(runner_id)
        out.append(
            {
                "runner_id": runner_id,
                "runner_label": token.label if token else None,
                "runner_name": token.runner_name if token else None,
                "revoked": token.revoked if token else None,
                "total_runs_claimed": total,
                "status_counts": status_counts,
                "runner_lost_count": lost,
                "runner_lost_rate": round(lost / total, 4) if total else None,
                "pass_rate": round(passed / total, 4) if total else None,
            }
        )
    return sorted(out, key=lambda r: r["total_runs_claimed"], reverse=True)


def retry_frequency(db: Session) -> dict:
    """Denominator: every distinct (workflow_run_id, workflow_step_id)
    pair that has more than one WorkflowStepRun attempt. Reported as a
    count and a rate against all distinct step occurrences, not against
    raw attempt rows (a step retried 3 times is one retried occurrence,
    not three)."""
    rows = (
        db.query(models.WorkflowStepRun.workflow_run_id, models.WorkflowStepRun.workflow_step_id, func.max(models.WorkflowStepRun.attempt_number))
        .group_by(models.WorkflowStepRun.workflow_run_id, models.WorkflowStepRun.workflow_step_id)
        .all()
    )
    total_occurrences = len(rows)
    retried = sum(1 for *_key, max_attempt in rows if max_attempt > 1)
    return {
        "total_step_occurrences": total_occurrences,
        "retried_step_occurrences": retried,
        "retry_rate": round(retried / total_occurrences, 4) if total_occurrences else None,
    }


def runner_lost_frequency(db: Session) -> dict:
    """Denominator: every WorkflowRun row that ever reached a terminal
    status (RUNNER_LOST is one of those terminal statuses)."""
    total_terminal = (
        db.query(func.count(models.WorkflowRun.id))
        .filter(models.WorkflowRun.status.in_(models.WORKFLOW_RUN_TERMINAL_STATUSES))
        .scalar()
    )
    lost = db.query(func.count(models.WorkflowRun.id)).filter(models.WorkflowRun.status == "RUNNER_LOST").scalar()
    return {
        "total_terminal_runs": total_terminal,
        "runner_lost_runs": lost,
        "runner_lost_rate": round(lost / total_terminal, 4) if total_terminal else None,
    }


def evidence_completeness_hybrid(db: Session) -> dict:
    """Denominator: every WorkflowStepRun whose step_type is SCREENSHOT
    or MANUAL_CHECKPOINT (the two step kinds where evidence is
    expected) that reached a terminal PASSED/FAILED status."""
    expected_step_ids = [
        row[0]
        for row in db.query(models.WorkflowStep.id).filter(models.WorkflowStep.step_type.in_(["SCREENSHOT", "MANUAL_CHECKPOINT"])).all()
    ]
    if not expected_step_ids:
        return {"expected_step_runs": 0, "step_runs_with_evidence": 0, "completeness_rate": None}
    expected_step_runs = (
        db.query(func.count(models.WorkflowStepRun.id))
        .filter(
            models.WorkflowStepRun.workflow_step_id.in_(expected_step_ids),
            models.WorkflowStepRun.status.in_(["PASSED", "FAILED"]),
        )
        .scalar()
    )
    step_run_ids_with_evidence = {
        row[0]
        for row in db.query(models.EvidenceItem.workflow_step_run_id)
        .filter(models.EvidenceItem.workflow_step_run_id.isnot(None), models.EvidenceItem.status == "ACTIVE")
        .distinct()
        .all()
    }
    with_evidence = (
        db.query(func.count(models.WorkflowStepRun.id))
        .filter(
            models.WorkflowStepRun.workflow_step_id.in_(expected_step_ids),
            models.WorkflowStepRun.status.in_(["PASSED", "FAILED"]),
            models.WorkflowStepRun.id.in_(step_run_ids_with_evidence) if step_run_ids_with_evidence else False,
        )
        .scalar()
    )
    return {
        "expected_step_runs": expected_step_runs,
        "step_runs_with_evidence": with_evidence,
        "completeness_rate": round(with_evidence / expected_step_runs, 4) if expected_step_runs else None,
    }


def defect_linkage(db: Session) -> dict:
    """Denominator: every Defect row created from a hybrid run/step/
    checkpoint (workflow_run_id is not null) vs. the total defect count
    in this project — shows what fraction of defects have hybrid
    provenance at all, distinct from Track A's own manually-linked
    defects."""
    total = db.query(func.count(models.Defect.id)).scalar()
    hybrid_linked = db.query(func.count(models.Defect.id)).filter(models.Defect.workflow_run_id.isnot(None)).scalar()
    return {"total_defects": total, "hybrid_linked_defects": hybrid_linked}


def workflows_with_frequent_failures(db: Session, limit: int = 10) -> list[dict]:
    """Denominator per workflow: every terminal run of any of its
    revisions. Only workflows with at least one terminal run appear."""
    rows = (
        db.query(
            models.WorkflowDefinition.id,
            models.WorkflowDefinition.name,
            models.WorkflowRun.status,
            func.count(models.WorkflowRun.id),
        )
        .join(models.WorkflowRevision, models.WorkflowRevision.workflow_id == models.WorkflowDefinition.id)
        .join(models.WorkflowRun, models.WorkflowRun.workflow_revision_id == models.WorkflowRevision.id)
        .filter(models.WorkflowRun.status.in_(models.WORKFLOW_RUN_TERMINAL_STATUSES))
        .group_by(models.WorkflowDefinition.id, models.WorkflowDefinition.name, models.WorkflowRun.status)
        .all()
    )
    by_workflow: dict[int, dict] = {}
    for wf_id, name, status, n in rows:
        entry = by_workflow.setdefault(wf_id, {"workflow_id": wf_id, "workflow_name": name, "total_terminal_runs": 0, "failed_runs": 0})
        entry["total_terminal_runs"] += n
        if status in ("FAILED", "BLOCKED", "RUNNER_LOST", "SYSTEM_ERROR"):
            entry["failed_runs"] += n
    out = []
    for entry in by_workflow.values():
        entry["failure_rate"] = round(entry["failed_runs"] / entry["total_terminal_runs"], 4) if entry["total_terminal_runs"] else None
        out.append(entry)
    return sorted(out, key=lambda e: (e["failure_rate"] or 0), reverse=True)[:limit]


def slowest_workflow_steps(db: Session, limit: int = 10) -> list[dict]:
    """Denominator: WorkflowStepRun rows with both started_at and
    ended_at set (a step that never finished contributes no data
    point). Average duration per (workflow_step_id) grouping."""
    rows = (
        db.query(
            models.WorkflowStepRun.workflow_step_id,
            models.WorkflowStep.description,
            func.count(models.WorkflowStepRun.id),
        )
        .join(models.WorkflowStep, models.WorkflowStep.id == models.WorkflowStepRun.workflow_step_id)
        .filter(models.WorkflowStepRun.started_at.isnot(None), models.WorkflowStepRun.ended_at.isnot(None))
        .group_by(models.WorkflowStepRun.workflow_step_id, models.WorkflowStep.description)
        .all()
    )
    out = []
    for step_id, desc, n in rows:
        durations = (
            db.query(models.WorkflowStepRun.started_at, models.WorkflowStepRun.ended_at)
            .filter(
                models.WorkflowStepRun.workflow_step_id == step_id,
                models.WorkflowStepRun.started_at.isnot(None),
                models.WorkflowStepRun.ended_at.isnot(None),
            )
            .all()
        )
        secs = [(ended - started).total_seconds() for started, ended in durations]
        avg = sum(secs) / len(secs) if secs else None
        out.append({"workflow_step_id": step_id, "step_description": desc, "sample_count": n, "avg_duration_seconds": round(avg, 3) if avg is not None else None})
    return sorted(out, key=lambda e: (e["avg_duration_seconds"] or 0), reverse=True)[:limit]


def recent_hybrid_activity(db: Session, limit: int = 30) -> list[dict]:
    """Most recent runner_execution_events across all runs, newest
    first, capped at `limit` — never the full unbounded event log."""
    events = db.query(models.RunnerExecutionEvent).order_by(models.RunnerExecutionEvent.id.desc()).limit(limit).all()
    return [
        {
            "id": e.id,
            "workflow_run_id": e.workflow_run_id,
            "event_type": e.event_type,
            "actor_type": e.actor_type,
            "created_at": e.created_at,
        }
        for e in events
    ]


def checkpoint_waiting_summary(db: Session) -> dict:
    """Average/max checkpoint waiting duration across every decided
    checkpoint. Denominator: WorkflowCheckpointDecision rows (a decision
    exists only once a human actually decided, so an unbounded pending
    checkpoint doesn't skew the average)."""
    decisions = db.query(models.WorkflowCheckpointDecision).all()
    durations = []
    for d in decisions:
        run = db.query(models.WorkflowRun).filter(models.WorkflowRun.id == d.workflow_run_id).first()
        if run is None:
            continue
    # Waiting duration per decision is computed from the event log (see
    # hybrid_timing.checkpoint_timings) rather than duplicated here to
    # avoid two different answers for the same number; this summary
    # aggregates across every run's checkpoints.
    from . import hybrid_timing

    all_waits = []
    run_ids = {d.workflow_run_id for d in decisions}
    for run_id in run_ids:
        for cp in hybrid_timing.checkpoint_timings(db, run_id):
            if cp["checkpoint_waiting_duration_seconds"] is not None:
                all_waits.append(cp["checkpoint_waiting_duration_seconds"])
    return {
        "decided_checkpoint_count": len(all_waits),
        "avg_waiting_seconds": round(sum(all_waits) / len(all_waits), 3) if all_waits else None,
        "max_waiting_seconds": round(max(all_waits), 3) if all_waits else None,
        "min_waiting_seconds": round(min(all_waits), 3) if all_waits else None,
    }
