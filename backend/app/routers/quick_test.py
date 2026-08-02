"""Quick Manual Test entry flow -- reduces time-to-first-test by
atomically creating the exact same real domain objects a tester would
otherwise create by hand across several screens (TestSuite ->
ScriptRevision -> TestCase -> publish -> TestCycle -> CycleTestResult),
then handing back the execution URL directly. No parallel ad-hoc
testing model -- every row created here is a completely ordinary,
fully auditable, fully exportable row in the exact same tables Track A
already uses; the only new behavior is doing all of it in one
transaction from one small form instead of five separate screens.

Deliberately its own top-level router (prefix /api/{slug}, no fixed
suffix) rather than nested under /cycles or /suites, so its two static
paths (/quick-test, /continue-last-test) can never collide with an
existing dynamic /{id}-shaped route in another router regardless of
registration order.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_project_db
from ..auth import get_current_user, require_tester
from .cycles import create_cycle_with_snapshot, most_recently_used_environment, _to_out as _cycle_to_out

router = APIRouter(prefix="/api/{slug}", tags=["quick-test"])

QUICK_TESTS_SUITE_NAME = "Quick Tests"


def _get_or_create_quick_tests_suite(db: Session, user_email: str) -> models.TestSuite:
    suite = (
        db.query(models.TestSuite)
        .filter(models.TestSuite.name == QUICK_TESTS_SUITE_NAME, models.TestSuite.is_system_generated.is_(True))
        .first()
    )
    if suite:
        return suite
    suite = models.TestSuite(
        name=QUICK_TESTS_SUITE_NAME,
        description="Auto-created container for Quick Manual Test entries. Each entry is its own published revision/case, fully real and exportable — hidden from the formal suite list by default.",
        suite_type="OTHER",
        is_system_generated=True,
        created_by=user_email,
    )
    db.add(suite)
    db.flush()
    return suite


@router.post("/quick-test", response_model=schemas.QuickTestOut)
def create_quick_test(
    slug: str,
    payload: schemas.QuickTestCreate,
    db: Session = Depends(get_project_db),
    user: models.User = Depends(require_tester),
):
    if not payload.title.strip():
        raise HTTPException(status_code=400, detail="title is required")

    suite = _get_or_create_quick_tests_suite(db, user.email)
    timestamp = datetime.utcnow()
    label = f"quick-{timestamp.strftime('%Y%m%d%H%M%S%f')}"

    revision = models.ScriptRevision(
        suite_id=suite.id,
        revision_label=label,
        revision_number_sort=int(timestamp.strftime("%Y%m%d%H%M%S")),
        status="DRAFT",
        change_summary=f"Quick Manual Test: {payload.title}",
        source_type="MANUAL",
        imported_at=timestamp,
        imported_by=user.email,
    )
    db.add(revision)
    db.flush()

    case = models.TestCase(
        suite_id=suite.id,
        revision_id=revision.id,
        checkpoint_code=label.upper(),
        title=payload.title.strip(),
        action_md="Manual ad-hoc test — see title/actual result.",
        expected_result_md=(payload.expected_result_md or "").strip(),
    )
    db.add(case)
    db.flush()

    # Publish immediately -- a Quick Manual Test has no separate draft-
    # review step by design (the whole point is skipping ceremony for a
    # one-off manual check); it is still a real, immutable, PUBLISHED
    # revision exactly like any hand-authored one, never a bypass of the
    # revision-immutability rule itself.
    revision.status = "PUBLISHED"
    revision.published_at = timestamp
    revision.published_by = user.email

    environment = (payload.environment or most_recently_used_environment(db)).strip() or most_recently_used_environment(db)
    cycle = create_cycle_with_snapshot(
        db, user.email,
        suite_id=suite.id, script_revision_id=revision.id,
        name=f"Quick Test: {payload.title.strip()}",
        environment=environment,
        require_evidence_for_pass=payload.require_evidence_for_pass,
        is_system_generated=True,
    )
    db.commit()
    db.refresh(cycle)

    result = db.query(models.CycleTestResult).filter(models.CycleTestResult.cycle_id == cycle.id).first()
    return schemas.QuickTestOut(cycle=_cycle_to_out(db, cycle), result_id=result.id)


@router.get("/continue-last-test", response_model=schemas.ContinueLastTestOut)
def continue_last_test(slug: str, db: Session = Depends(get_project_db), user: models.User = Depends(get_current_user)):
    """Finds where this tester (or, failing that, anyone) last left off
    in an in-progress cycle, so the Dashboard's "Continue last test" can
    jump straight back to the exact case, not just the cycle."""
    result = (
        db.query(models.CycleTestResult)
        .join(models.TestCycle, models.TestCycle.id == models.CycleTestResult.cycle_id)
        .filter(models.TestCycle.status == "IN_PROGRESS", models.CycleTestResult.executed_by == user.email)
        .order_by(models.CycleTestResult.updated_at.desc())
        .first()
    )
    if not result:
        result = (
            db.query(models.CycleTestResult)
            .join(models.TestCycle, models.TestCycle.id == models.CycleTestResult.cycle_id)
            .filter(models.TestCycle.status == "IN_PROGRESS")
            .order_by(models.CycleTestResult.updated_at.desc())
            .first()
        )
    if not result:
        raise HTTPException(status_code=404, detail="No in-progress test to continue")
    return schemas.ContinueLastTestOut(cycle_id=result.cycle_id, result_id=result.id)
