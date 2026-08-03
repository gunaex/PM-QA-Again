import json

from sqlalchemy import func
from sqlalchemy.orm import Session

from . import models


def project_storage_usage_bytes(project_db: Session) -> int:
    """Sums ALL evidence for the project — ACTIVE and ARCHIVED both still
    occupy real storage (requirement 9); only a future purge feature
    would actually free space."""
    evidence_total = project_db.query(func.sum(models.EvidenceItem.original_size_bytes)).scalar() or 0
    screenshot_total = project_db.query(func.sum(models.WorkflowRunScreenshot.size_bytes)).scalar() or 0
    return evidence_total + screenshot_total


def quota_status(project: models.Project, project_db: Session) -> dict:
    used = project_storage_usage_bytes(project_db)
    quota = project.storage_quota_bytes
    try:
        thresholds = sorted(json.loads(project.storage_warning_thresholds))
    except (TypeError, ValueError):
        thresholds = [70, 85, 95, 100]

    percent_used = round((used / quota) * 100, 2) if quota else 0.0
    threshold_level = 0
    for t in thresholds:
        if percent_used >= t:
            threshold_level = t

    return {
        "used_bytes": used,
        "quota_bytes": quota,
        "percent_used": percent_used,
        "threshold_level": threshold_level,
        "thresholds": thresholds,
        "over_quota": used >= quota,
    }
