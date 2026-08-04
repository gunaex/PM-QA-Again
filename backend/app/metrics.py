"""Dashboard/report metric formulas — see the Phase 6 restatement for
why each denominator was chosen; the master spec left these genuinely
undefined beyond "make it explicit" and "don't count NOT_RUN as PASS."
"""

from datetime import datetime, date

from sqlalchemy.orm import Session

from . import models


def active_cycle(db: Session) -> models.TestCycle | None:
    """"Active cycle" isn't defined in the spec either — resolved here as
    the most recently created non-CANCELLED cycle. Documented choice."""
    return (
        db.query(models.TestCycle)
        .filter(models.TestCycle.status != "CANCELLED")
        .order_by(models.TestCycle.created_at.desc())
        .first()
    )


def result_counts(db: Session, cycle_id: int, date_from: date | None = None, date_to: date | None = None) -> dict:
    counts = {s: 0 for s in models.RESULT_STATUSES}
    q = db.query(models.CycleTestResult.status, models.CycleTestResult.id).filter(
        models.CycleTestResult.cycle_id == cycle_id
    )
    if date_from:
        q = q.filter(models.CycleTestResult.executed_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        q = q.filter(models.CycleTestResult.executed_at <= datetime.combine(date_to, datetime.max.time()))
    for status, _id in q:
        counts[status] += 1
    return counts


def pass_rate(db: Session, cycle_id: int, counts: dict | None = None, date_from: date | None = None, date_to: date | None = None) -> dict:
    if counts is None:
        counts = result_counts(db, cycle_id, date_from=date_from, date_to=date_to)
    total = sum(counts.values())
    approved_na = (
        db.query(models.CycleTestResult.id)
        .filter(
            models.CycleTestResult.cycle_id == cycle_id,
            models.CycleTestResult.status == "NOT_APPLICABLE",
            models.CycleTestResult.review_status == "ACCEPTED",
        )
        .count()
    )
    denominator = total - approved_na
    numerator = counts["PASS"]
    percent = round((numerator / denominator) * 100, 2) if denominator else 0.0
    return {
        "numerator": numerator,
        "denominator": denominator,
        "percent": percent,
        "formula": "PASS / (total_cases - approved_NOT_APPLICABLE); NOT_RUN stays in the denominator",
    }


def evidence_completeness(db: Session, cycle_id: int) -> dict:
    executed_ids = [
        row[0]
        for row in db.query(models.CycleTestResult.id)
        .filter(models.CycleTestResult.cycle_id == cycle_id, models.CycleTestResult.status != "NOT_RUN")
        .all()
    ]
    if not executed_ids:
        return {"numerator": 0, "denominator": 0, "percent": 0.0, "formula": "executed results with >=1 ACTIVE evidence item / executed results"}
    with_evidence = (
        db.query(models.EvidenceItem.cycle_test_result_id)
        .filter(models.EvidenceItem.cycle_test_result_id.in_(executed_ids), models.EvidenceItem.status == "ACTIVE")
        .distinct()
        .count()
    )
    percent = round((with_evidence / len(executed_ids)) * 100, 2)
    return {
        "numerator": with_evidence,
        "denominator": len(executed_ids),
        "percent": percent,
        "formula": "executed results with >=1 ACTIVE evidence item / executed results",
    }


def go_live_readiness(db: Session, cycle_id: int) -> dict:
    blockers = []

    p0_bad_status = (
        db.query(models.CycleTestResult.id, models.TestCase.checkpoint_code, models.CycleTestResult.status)
        .join(models.TestCase, models.TestCase.id == models.CycleTestResult.test_case_id)
        .filter(
            models.CycleTestResult.cycle_id == cycle_id,
            models.TestCase.priority == "P0",
            models.CycleTestResult.status.in_(["FAIL", "BLOCKED", "NOT_RUN"]),
        )
        .all()
    )
    for _id, checkpoint_code, status in p0_bad_status:
        blockers.append(f"{checkpoint_code} is P0 and {status}")

    p0_unreviewed_na = (
        db.query(models.TestCase.checkpoint_code)
        .join(models.CycleTestResult, models.CycleTestResult.test_case_id == models.TestCase.id)
        .filter(
            models.CycleTestResult.cycle_id == cycle_id,
            models.TestCase.priority == "P0",
            models.CycleTestResult.status == "NOT_APPLICABLE",
            models.CycleTestResult.review_status != "ACCEPTED",
        )
        .all()
    )
    for (checkpoint_code,) in p0_unreviewed_na:
        blockers.append(f"{checkpoint_code} is P0 NOT_APPLICABLE and not yet admin-approved")

    open_high_severity_defects = (
        db.query(models.Defect.defect_key, models.Defect.severity)
        .filter(
            models.Defect.cycle_id == cycle_id,
            models.Defect.severity.in_(["P0", "P1"]),
            models.Defect.status.in_(models.DEFECT_OPEN_STATUSES),
        )
        .all()
    )
    for defect_key, severity in open_high_severity_defects:
        blockers.append(f"{defect_key} is open and {severity}")

    return {
        "ready": len(blockers) == 0,
        "blockers": blockers,
        "formula": "ready iff no P0 case is FAIL/BLOCKED/NOT_RUN, no P0 NOT_APPLICABLE case is unapproved, "
        "and no open P0/P1 defect is linked to this cycle",
    }
