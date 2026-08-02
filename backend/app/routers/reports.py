from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models
from ..database import get_project_db, get_master_db
from ..auth import require_project_access
from ..quota import quota_status
from ..metrics import result_counts, pass_rate, evidence_completeness, go_live_readiness

router = APIRouter(prefix="/api/{slug}/reports", tags=["reports"], dependencies=[Depends(require_project_access)])

# Maps report #5/#6's "stable checkpoint/logical case key" comparison
# requirement (rebuild prompt §11) onto content_sha256 for change
# detection — same fields already used by the case-editor's own hashing.


def _get_cycle(db: Session, cycle_id: int) -> models.TestCycle:
    cycle = db.query(models.TestCycle).filter(models.TestCycle.id == cycle_id).first()
    if not cycle:
        raise HTTPException(status_code=404, detail="Cycle not found")
    return cycle


# ---------- 1. Execution Summary ----------


@router.get("/execution-summary")
def execution_summary(slug: str, cycle_id: int, db: Session = Depends(get_project_db)):
    cycle = _get_cycle(db, cycle_id)
    counts = result_counts(db, cycle_id)
    return {
        "cycle": {"id": cycle.id, "name": cycle.name, "status": cycle.status, "environment": cycle.environment},
        "result_counts": counts,
        "pass_rate": pass_rate(db, cycle_id, counts=counts),
        "evidence_completeness": evidence_completeness(db, cycle_id),
    }


# ---------- 2. Detailed Test Result ----------


@router.get("/detailed-results")
def detailed_results(
    slug: str,
    cycle_id: int,
    status: str | None = None,
    tester: str | None = None,
    checkpoint_code: str | None = None,
    db: Session = Depends(get_project_db),
):
    _get_cycle(db, cycle_id)
    q = (
        db.query(models.CycleTestResult, models.TestCase)
        .join(models.TestCase, models.TestCase.id == models.CycleTestResult.test_case_id)
        .filter(models.CycleTestResult.cycle_id == cycle_id)
    )
    if status:
        q = q.filter(models.CycleTestResult.status == status)
    if tester:
        q = q.filter(models.CycleTestResult.executed_by == tester)
    if checkpoint_code:
        q = q.filter(models.TestCase.checkpoint_code == checkpoint_code)

    rows = []
    for result, case in q.order_by(models.TestCase.sequence_no).all():
        evidence_count = (
            db.query(models.EvidenceItem.id)
            .filter(models.EvidenceItem.cycle_test_result_id == result.id, models.EvidenceItem.status == "ACTIVE")
            .count()
        )
        rows.append(
            {
                "checkpoint_code": case.checkpoint_code,
                "title": case.title,
                "priority": case.priority,
                "status": result.status,
                "actual_result_md": result.actual_result_md,
                "executed_by": result.executed_by,
                "executed_at": result.executed_at,
                "review_status": result.review_status,
                "defect_reference": result.defect_reference,
                "evidence_count": evidence_count,
            }
        )
    return rows


# ---------- 3. NG and Defect Report ----------


@router.get("/ng-defects")
def ng_defects(slug: str, cycle_id: int, db: Session = Depends(get_project_db)):
    _get_cycle(db, cycle_id)
    ng_cases = (
        db.query(models.CycleTestResult, models.TestCase)
        .join(models.TestCase, models.TestCase.id == models.CycleTestResult.test_case_id)
        .filter(models.CycleTestResult.cycle_id == cycle_id, models.CycleTestResult.status == "FAIL")
        .all()
    )
    defects = db.query(models.Defect).filter(models.Defect.cycle_id == cycle_id).all()
    return {
        "ng_cases": [
            {
                "checkpoint_code": case.checkpoint_code,
                "title": case.title,
                "actual_result_md": result.actual_result_md,
                "defect_reference": result.defect_reference,
            }
            for result, case in ng_cases
        ],
        "defects": [
            {
                "defect_key": d.defect_key,
                "title": d.title,
                "severity": d.severity,
                "status": d.status,
                "external_url": d.external_url,
            }
            for d in defects
        ],
    }


# ---------- 4. Evidence Completeness ----------


@router.get("/evidence-completeness")
def evidence_completeness_report(slug: str, cycle_id: int, db: Session = Depends(get_project_db)):
    _get_cycle(db, cycle_id)
    summary = evidence_completeness(db, cycle_id)
    missing = (
        db.query(models.CycleTestResult, models.TestCase)
        .join(models.TestCase, models.TestCase.id == models.CycleTestResult.test_case_id)
        .filter(models.CycleTestResult.cycle_id == cycle_id, models.CycleTestResult.status != "NOT_RUN")
        .all()
    )
    missing_checkpoints = []
    for result, case in missing:
        has_evidence = (
            db.query(models.EvidenceItem.id)
            .filter(models.EvidenceItem.cycle_test_result_id == result.id, models.EvidenceItem.status == "ACTIVE")
            .first()
        )
        if not has_evidence:
            missing_checkpoints.append(case.checkpoint_code)
    return {**summary, "missing_evidence_checkpoints": missing_checkpoints}


# ---------- 5. Revision Comparison ----------


@router.get("/revision-comparison")
def revision_comparison(slug: str, revision_a_id: int, revision_b_id: int, db: Session = Depends(get_project_db)):
    cases_a = {c.checkpoint_code: c for c in db.query(models.TestCase).filter(models.TestCase.revision_id == revision_a_id).all()}
    cases_b = {c.checkpoint_code: c for c in db.query(models.TestCase).filter(models.TestCase.revision_id == revision_b_id).all()}

    added = sorted(set(cases_b) - set(cases_a))
    removed = sorted(set(cases_a) - set(cases_b))
    common = set(cases_a) & set(cases_b)
    changed = sorted(cp for cp in common if cases_a[cp].content_sha256 != cases_b[cp].content_sha256)
    unchanged = sorted(cp for cp in common if cases_a[cp].content_sha256 == cases_b[cp].content_sha256)

    return {"added": added, "removed": removed, "changed": changed, "unchanged": unchanged}


# ---------- 6. Cycle-to-Cycle Comparison ----------


@router.get("/cycle-comparison")
def cycle_comparison(slug: str, cycle_a_id: int, cycle_b_id: int, db: Session = Depends(get_project_db)):
    def results_by_checkpoint(cycle_id):
        rows = (
            db.query(models.CycleTestResult, models.TestCase)
            .join(models.TestCase, models.TestCase.id == models.CycleTestResult.test_case_id)
            .filter(models.CycleTestResult.cycle_id == cycle_id)
            .all()
        )
        return {case.checkpoint_code: result.status for result, case in rows}

    a = results_by_checkpoint(cycle_a_id)
    b = results_by_checkpoint(cycle_b_id)
    transitions = []
    for checkpoint in sorted(set(a) | set(b)):
        from_status = a.get(checkpoint, "ABSENT")
        to_status = b.get(checkpoint, "ABSENT")
        transitions.append({"checkpoint_code": checkpoint, "from": from_status, "to": to_status, "changed": from_status != to_status})
    return transitions


# ---------- 7. Tester Progress ----------


@router.get("/tester-progress")
def tester_progress(slug: str, cycle_id: int, db: Session = Depends(get_project_db)):
    _get_cycle(db, cycle_id)
    rows = (
        db.query(models.CycleTestResult.executed_by, models.CycleTestResult.status, models.CycleTestResult.id)
        .filter(models.CycleTestResult.cycle_id == cycle_id, models.CycleTestResult.executed_by.isnot(None))
        .all()
    )
    by_tester: dict[str, dict[str, int]] = {}
    for executed_by, status, _id in rows:
        by_tester.setdefault(executed_by, {s: 0 for s in models.RESULT_STATUSES})
        by_tester[executed_by][status] += 1
    return [{"tester": tester, "counts": counts, "total_executed": sum(counts.values())} for tester, counts in by_tester.items()]


# ---------- 8. Go-Live Readiness ----------


@router.get("/go-live-readiness")
def go_live_readiness_report(slug: str, cycle_id: int, db: Session = Depends(get_project_db)):
    _get_cycle(db, cycle_id)
    return go_live_readiness(db, cycle_id)


# ---------- 9. Audit/Sign-off Summary ----------


@router.get("/signoff-summary")
def signoff_summary(slug: str, cycle_id: int, db: Session = Depends(get_project_db)):
    _get_cycle(db, cycle_id)
    signoffs = db.query(models.SignOff).filter(models.SignOff.cycle_id == cycle_id).order_by(models.SignOff.acted_at).all()
    return [
        {
            "signoff_type": s.signoff_type,
            "decision": s.decision,
            "comment_md": s.comment_md,
            "actor": s.actor,
            "acted_at": s.acted_at,
        }
        for s in signoffs
    ]


# ---------- 10. Project Storage Usage ----------


@router.get("/storage-usage")
def storage_usage(slug: str, db: Session = Depends(get_project_db), master_db: Session = Depends(get_master_db)):
    project = master_db.query(models.Project).filter(models.Project.slug == slug).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return quota_status(project, db)
