"""HYB-5: hybrid (Track B) dashboard, reports, and timing/trend endpoints.

Deliberately a separate router/prefix from dashboard.py/reports.py
(Track A) — never touches those existing formulas. All endpoints here
are read-only aggregates over workflow_run*/runner_execution_events/
workflow_checkpoint_decisions, following the same lightweight-payload/
grouped-aggregate/no-N+1 discipline as docs/PERFORMANCE_FAST_PASS.md.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, hybrid_metrics, hybrid_timing
from ..database import get_project_db, get_master_db
from ..auth import get_current_user

router = APIRouter(prefix="/api/{slug}/hybrid-reports", tags=["hybrid-reports"], dependencies=[Depends(get_current_user)])


def _get_run(db: Session, run_id: int) -> models.WorkflowRun:
    run = db.query(models.WorkflowRun).filter(models.WorkflowRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Workflow run not found")
    return run


@router.get("/dashboard")
def hybrid_dashboard(slug: str, db: Session = Depends(get_project_db), master_db: Session = Depends(get_master_db)):
    return {
        "run_status_counts": hybrid_metrics.run_status_counts(db),
        "provenance": hybrid_metrics.provenance_summary(db),
        "runner_reliability": hybrid_metrics.runner_reliability(db, master_db),
        "runner_lost_frequency": hybrid_metrics.runner_lost_frequency(db),
        "retry_frequency": hybrid_metrics.retry_frequency(db),
        "checkpoint_waiting_summary": hybrid_metrics.checkpoint_waiting_summary(db),
        "evidence_completeness": hybrid_metrics.evidence_completeness_hybrid(db),
        "defect_linkage": hybrid_metrics.defect_linkage(db),
        "recent_activity": hybrid_metrics.recent_hybrid_activity(db),
    }


@router.get("/locator-failures")
def locator_failures(slug: str, db: Session = Depends(get_project_db)):
    return hybrid_metrics.locator_failure_frequency(db)


@router.get("/failure-categories")
def failure_categories(slug: str, db: Session = Depends(get_project_db)):
    return hybrid_metrics.failure_category_breakdown(db)


@router.get("/workflows-frequent-failures")
def frequent_failures(slug: str, db: Session = Depends(get_project_db)):
    return hybrid_metrics.workflows_with_frequent_failures(db)


@router.get("/slowest-steps")
def slowest_steps(slug: str, db: Session = Depends(get_project_db)):
    return hybrid_metrics.slowest_workflow_steps(db)


@router.get("/runner-reliability")
def runner_reliability_report(slug: str, db: Session = Depends(get_project_db), master_db: Session = Depends(get_master_db)):
    return hybrid_metrics.runner_reliability(db, master_db)


# ---------- timing ----------


@router.get("/timing/runs/{run_id}")
def run_timing_report(slug: str, run_id: int, db: Session = Depends(get_project_db)):
    run = _get_run(db, run_id)
    return hybrid_timing.run_timing(db, run)


@router.get("/timing/run-trend")
def run_trend_report(slug: str, workflow_id: int, limit: int = 50, db: Session = Depends(get_project_db)):
    """Trend view: this workflow's total run duration across its
    history, oldest first — never overwrites/recomputes past runs, just
    reads their existing timestamps."""
    return hybrid_timing.run_duration_trend(db, workflow_id, limit=limit)


@router.get("/timing/step-trend")
def step_trend_report(slug: str, workflow_id: int, step_description: str, limit: int = 50, db: Session = Depends(get_project_db)):
    """Trend view for one logical step (matched by exact description)
    across every run of the given workflow — e.g. "Save Customer: Run 1
    1.2s, Run 2 1.5s, Run 3 2.8s". See hybrid_timing.step_duration_trend
    for the exact-description-match limitation."""
    return hybrid_timing.step_duration_trend(db, workflow_id, step_description, limit=limit)
