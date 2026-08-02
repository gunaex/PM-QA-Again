from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models
from ..database import get_project_db, get_master_db
from ..auth import require_project_access
from ..quota import quota_status
from ..metrics import active_cycle, result_counts, pass_rate, evidence_completeness, go_live_readiness

router = APIRouter(prefix="/api/{slug}/dashboard", tags=["dashboard"], dependencies=[Depends(require_project_access)])


@router.get("")
def get_dashboard(slug: str, db: Session = Depends(get_project_db), master_db: Session = Depends(get_master_db)):
    cycle = active_cycle(db)
    if not cycle:
        return {"cycle": None, "message": "No test cycles yet."}

    counts = result_counts(db, cycle.id)

    open_defects_by_severity = {s: 0 for s in models.DEFECT_SEVERITIES}
    for severity, _id in (
        db.query(models.Defect.severity, models.Defect.id)
        .filter(models.Defect.cycle_id == cycle.id, models.Defect.status.in_(models.DEFECT_OPEN_STATUSES))
        .all()
    ):
        open_defects_by_severity[severity] += 1

    pending_reviews = (
        db.query(models.CycleTestResult.id)
        .filter(
            models.CycleTestResult.cycle_id == cycle.id,
            models.CycleTestResult.status == "NOT_APPLICABLE",
            models.CycleTestResult.review_status == "UNREVIEWED",
        )
        .count()
    )

    project = master_db.query(models.Project).filter(models.Project.slug == slug).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    recent_activity = (
        db.query(models.ActivityLog).order_by(models.ActivityLog.changed_at.desc()).limit(20).all()
    )

    return {
        "cycle": {
            "id": cycle.id,
            "name": cycle.name,
            "status": cycle.status,
            "environment": cycle.environment,
        },
        "total_cases": sum(counts.values()),
        "result_counts": counts,
        "pass_rate": pass_rate(db, cycle.id, counts=counts),
        "evidence_completeness": evidence_completeness(db, cycle.id),
        "go_live_readiness": go_live_readiness(db, cycle.id),
        "open_defects_by_severity": open_defects_by_severity,
        "pending_na_reviews": pending_reviews,
        "storage_usage": quota_status(project, db),
        "recent_activity": [
            {
                "entity_type": a.entity_type,
                "entity_id": a.entity_id,
                "field_changed": a.field_changed,
                "old_value": a.old_value,
                "new_value": a.new_value,
                "changed_by": a.changed_by,
                "changed_at": a.changed_at,
            }
            for a in recent_activity
        ],
    }
