"""Portable evidence package (rebuild prompt §17 "Portable Evidence
Package"). Built entirely server-side and in-memory:

- ZIP bytes assembled in an io.BytesIO — no filesystem temp files, so
  there's nothing to clean up (Phase 6 restatement's temp-file/cleanup
  strategy).
- Every evidence file is read via EvidenceStorage.get() — never a
  presigned URL, per the explicit requirement that the portable package
  must contain the actual bytes, not a link substitute (requirement 2).
- A missing object (see docs/EVIDENCE_STORAGE_LIFECYCLE.md) is recorded
  in the manifest as "missing": true and skipped, not a hard failure of
  the whole export — one bad row shouldn't block an otherwise-complete
  package.
"""

import hashlib
import io
import json
import re
import zipfile
from datetime import datetime, timezone

from . import models, hybrid_timing
from .report_excel import build_workbook, workbook_to_bytes, evidence_code
from .storage import EvidenceStorage


def _safe_slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "-", text.strip()).strip("-") or "item"


def _render_report_html(project: models.Project, cycle: models.TestCycle, counts: dict, pass_rate: dict) -> str:
    rows = "".join(f"<tr><td>{status}</td><td>{count}</td></tr>" for status, count in counts.items())
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{project.name} — {cycle.name}</title>
<style>
  body {{ font-family: system-ui, sans-serif; margin: 2rem; color: #111; }}
  table {{ border-collapse: collapse; margin-top: 1rem; }}
  td, th {{ border: 1px solid #ccc; padding: 4px 10px; text-align: left; }}
  @media print {{ body {{ margin: 0.5in; }} }}
</style></head>
<body>
  <h1>{project.name}</h1>
  <h2>{cycle.name} &mdash; {cycle.environment}</h2>
  <p>Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}</p>
  <h3>Result Summary</h3>
  <table><tr><th>Status</th><th>Count</th></tr>{rows}</table>
  <p>Pass rate: {pass_rate['percent']}% ({pass_rate['formula']})</p>
  <p>See the accompanying .xlsx for full detailed results, defects, evidence index, revision history, and sign-off records.</p>
</body></html>"""


def build_evidence_package(
    db,
    project: models.Project,
    cycle: models.TestCycle,
    storage: EvidenceStorage,
    generated_by: str,
) -> tuple[bytes, str]:
    """Returns (zip_bytes, filename)."""
    from .metrics import result_counts, pass_rate as pass_rate_fn

    wb = build_workbook(db, project, cycle, generated_by)
    xlsx_bytes = workbook_to_bytes(wb)

    cases_by_result = {
        r.id: c
        for r, c in (
            db.query(models.CycleTestResult, models.TestCase)
            .join(models.TestCase, models.TestCase.id == models.CycleTestResult.test_case_id)
            .filter(models.CycleTestResult.cycle_id == cycle.id)
            .all()
        )
    }
    evidence_items = db.query(models.EvidenceItem).filter(models.EvidenceItem.cycle_id == cycle.id).all()

    package_slug = f"{_safe_slug(project.slug)}_{_safe_slug(cycle.name)}"
    zip_buf = io.BytesIO()
    manifest_evidence = []

    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{package_slug}.xlsx", xlsx_bytes)
        zf.writestr(
            "report.html",
            _render_report_html(project, cycle, result_counts(db, cycle.id), pass_rate_fn(db, cycle.id)),
        )

        for item in evidence_items:
            case = cases_by_result.get(item.cycle_test_result_id)
            test_id = _safe_slug(case.checkpoint_code) if case else "unknown"
            ext = item.object_key.rsplit(".", 1)[-1] if "." in item.object_key else "bin"
            filename = f"{test_id}_{evidence_code(item.id)}.{ext}"

            missing = False
            checksum_verified = None
            try:
                content = storage.get(item.object_key)
            except Exception:
                missing = True
                content = None

            if content is not None:
                # Requirement: verify every included file against its
                # checksum before trusting it into the archive -- a
                # corrupted/tampered object is treated the same as a
                # missing one (excluded, flagged), never silently packaged.
                actual_sha256 = hashlib.sha256(content).hexdigest()
                checksum_verified = actual_sha256 == item.original_sha256
                if not checksum_verified:
                    missing = True
                    content = None

            archive_path = f"evidence/{filename}"
            if content is not None:
                zf.writestr(archive_path, content)

            defect = (
                db.query(models.Defect)
                .filter(models.Defect.cycle_test_result_id == item.cycle_test_result_id)
                .first()
                if item.cycle_test_result_id
                else None
            )

            manifest_evidence.append(
                {
                    "evidence_id": item.id,
                    "test_id": case.checkpoint_code if case else None,
                    # The exact in-archive path (not just a bare filename)
                    # so manifest.json -> zip entry lookup is a direct
                    # match, no prefix-guessing required by a consumer.
                    "filename": archive_path if not missing else None,
                    "sha256": item.original_sha256,
                    "checksum_verified": checksum_verified,
                    "size_bytes": item.original_size_bytes,
                    "status": item.status,
                    "captured_by": item.captured_by,
                    "captured_at": item.captured_at.isoformat() if item.captured_at else None,
                    "annotation_revision": item.current_revision_no,
                    "missing": missing,
                    # HYB-5: hybrid provenance links -- null for every
                    # Track A (tester-uploaded) evidence row.
                    "workflow_run_id": item.workflow_run_id,
                    "workflow_step_run_id": item.workflow_step_run_id,
                    "checkpoint_decision_id": item.checkpoint_decision_id,
                    "defect_key": defect.defect_key if defect else None,
                }
            )

        manifest = {
            "package_version": "1.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "generated_by": generated_by,
            "project": {"slug": project.slug, "name": project.name},
            "cycle": {
                "id": cycle.id,
                "name": cycle.name,
                "environment": cycle.environment,
                "status": cycle.status,
            },
            "evidence": manifest_evidence,
            "hybrid": _build_hybrid_manifest_section(db, cycle),
        }
        # default=str: hybrid_timing.run_timing embeds raw datetime objects
        # (run_created_at/started_at/ended_at on runs, steps, checkpoints,
        # evidence uploads) -- json.dumps can't serialize those natively.
        zf.writestr("manifest.json", json.dumps(manifest, indent=2, default=str))

    return zip_buf.getvalue(), f"{package_slug}_evidence_package.zip"


def _build_hybrid_manifest_section(db, cycle: models.TestCycle) -> dict:
    """Machine-readable links for every hybrid entity reachable from this
    cycle: workflow definition -> revision -> step -> run -> step run ->
    runner -> checkpoint -> human decision, with timestamps/durations.
    Never substitutes for the evidence bytes above -- this is metadata
    only, cross-referenced by id against the `evidence` list's own
    workflow_run_id/workflow_step_run_id/checkpoint_decision_id fields."""
    result_ids = [r.id for r in db.query(models.CycleTestResult.id).filter(models.CycleTestResult.cycle_id == cycle.id).all()]
    runs = (
        db.query(models.WorkflowRun).filter(models.WorkflowRun.cycle_test_result_id.in_(result_ids) if result_ids else False).all()
    )
    run_ids = [r.id for r in runs]
    revision_ids = sorted({r.workflow_revision_id for r in runs})
    revisions = db.query(models.WorkflowRevision).filter(models.WorkflowRevision.id.in_(revision_ids)).all() if revision_ids else []
    workflow_ids = sorted({r.workflow_id for r in revisions})
    workflows = db.query(models.WorkflowDefinition).filter(models.WorkflowDefinition.id.in_(workflow_ids)).all() if workflow_ids else []
    steps = db.query(models.WorkflowStep).filter(models.WorkflowStep.revision_id.in_(revision_ids)).all() if revision_ids else []
    step_runs = db.query(models.WorkflowStepRun).filter(models.WorkflowStepRun.workflow_run_id.in_(run_ids)).all() if run_ids else []
    decisions = db.query(models.WorkflowCheckpointDecision).filter(models.WorkflowCheckpointDecision.workflow_run_id.in_(run_ids)).all() if run_ids else []

    def iso(dt):
        return dt.isoformat() if dt else None

    return {
        "workflows": [{"id": w.id, "name": w.name, "status": w.status} for w in workflows],
        "workflow_revisions": [
            {"id": r.id, "workflow_id": r.workflow_id, "revision_label": r.revision_label, "status": r.status, "published_at": iso(r.published_at)}
            for r in revisions
        ],
        "workflow_steps": [
            {"id": s.id, "revision_id": s.revision_id, "sequence_no": s.sequence_no, "step_type": s.step_type, "description": s.description}
            for s in steps
        ],
        "workflow_runs": [
            {
                "id": r.id,
                "workflow_revision_id": r.workflow_revision_id,
                "cycle_test_result_id": r.cycle_test_result_id,
                "runner_id": r.runner_id,
                "status": r.status,
                "created_at": iso(r.created_at),
                "started_at": iso(r.started_at),
                "ended_at": iso(r.ended_at),
                "timing": hybrid_timing.run_timing(db, r),
            }
            for r in runs
        ],
        "workflow_step_runs": [
            {
                "id": sr.id,
                "workflow_run_id": sr.workflow_run_id,
                "workflow_step_id": sr.workflow_step_id,
                "attempt_number": sr.attempt_number,
                "status": sr.status,
                "failure_category": sr.failure_category,
                "duration_ms": sr.duration_ms,
                "started_at": iso(sr.started_at),
                "ended_at": iso(sr.ended_at),
            }
            for sr in step_runs
        ],
        "checkpoint_decisions": [
            {
                "id": d.id,
                "workflow_run_id": d.workflow_run_id,
                "workflow_step_id": d.workflow_step_id,
                "status": d.status,
                "decided_by_email": d.decided_by_email,
                "decided_at": iso(d.decided_at),
                "source": d.source,
                "resume_authorized": d.resume_authorized,
            }
            for d in decisions
        ],
    }
