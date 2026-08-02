"""HYB-5 acceptance gate (part 1): timing derivation and hybrid
dashboard/report endpoints, verified against the real running app
(TestClient) with a real runner-token client -- not mocked. Reuses the
same helper patterns as test_workflow_runs.py/test_workflow_checkpoints.py."""
import time

from fastapi.testclient import TestClient

from app.main import app

PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x02\x00\x00\x00\x02\x08\x02\x00\x00\x00\xfd\xd4\x9as"
    b"\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\xc0\xc0\xc0\x00\x00\x00\x06\x00\x03\xfa\xd0\x7f\xe6"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _fresh_client():
    c = TestClient(app)
    c.headers.update({"Origin": "http://localhost:5173"})
    return c


def _issue_runner_token(auth_client, label):
    r = auth_client.post("/api/runner-tokens", json={"label": label})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _make_published_workflow(auth_client, slug, name="timing wf", n_steps=2):
    wf = auth_client.post(f"/api/{slug}/workflows", json={"name": name}).json()
    rev = auth_client.post(f"/api/{slug}/workflows/{wf['id']}/revisions", json={"revision_label": "v1"}).json()
    step_ids = []
    for i in range(n_steps):
        s = auth_client.post(
            f"/api/{slug}/workflows/{wf['id']}/revisions/{rev['id']}/steps",
            json={"step_type": "SCREENSHOT", "description": f"timed step {i}"},
        ).json()
        step_ids.append(s["id"])
    pub = auth_client.post(f"/api/{slug}/workflows/{wf['id']}/revisions/{rev['id']}/publish")
    assert pub.status_code == 200, pub.text
    return wf["id"], rev["id"], step_ids


def _run_to_completion(auth_client, slug, revision_id, step_ids, label):
    queued = auth_client.post(f"/api/{slug}/workflow-runs", json={"workflow_revision_id": revision_id}).json()
    run_id = queued["id"]
    token = _issue_runner_token(auth_client, label)
    runner = _fresh_client()
    runner.headers.update({"X-Runner-Token": token})
    claim = runner.post(f"/api/{slug}/workflow-runs/claim").json()
    lease_token = claim["lease_token"]
    for step_id in step_ids:
        sr = runner.post(f"/api/{slug}/workflow-runs/{run_id}/step-runs", json={"workflow_step_id": step_id, "lease_token": lease_token}).json()
        time.sleep(0.01)
        runner.put(f"/api/{slug}/workflow-runs/{run_id}/step-runs/{sr['id']}", json={"status": "PASSED", "lease_token": lease_token})
    runner.post(f"/api/{slug}/workflow-runs/{run_id}/complete", json={"status": "PASSED", "lease_token": lease_token})
    return run_id


def test_run_timing_report_has_all_documented_buckets(auth_client, project_slug):
    slug = project_slug
    wf_id, revision_id, step_ids = _make_published_workflow(auth_client, slug, n_steps=2)
    run_id = _run_to_completion(auth_client, slug, revision_id, step_ids, "timing-runner-1")

    report = auth_client.get(f"/api/{slug}/hybrid-reports/timing/runs/{run_id}")
    assert report.status_code == 200, report.text
    body = report.json()

    assert body["run_id"] == run_id
    assert body["queue_delay_seconds"] is not None and body["queue_delay_seconds"] >= 0
    assert body["runner_claim_delay_seconds"] == body["queue_delay_seconds"]
    assert body["browser_startup_seconds"] is not None and body["browser_startup_seconds"] >= 0
    assert body["total_run_duration_seconds"] is not None and body["total_run_duration_seconds"] >= 0
    assert body["execution_duration_seconds"] is not None
    assert len(body["steps"]) == 2
    for s in body["steps"]:
        assert s["duration_seconds"] is not None and s["duration_seconds"] >= 0
        assert s["attempt_number"] == 1
        assert s["is_retry"] is False
    assert body["checkpoints"] == []


def test_evidence_upload_duration_is_recorded(auth_client, project_slug):
    slug = project_slug
    wf = auth_client.post(f"/api/{slug}/workflows", json={"name": "evidence timing wf"}).json()
    rev = auth_client.post(f"/api/{slug}/workflows/{wf['id']}/revisions", json={"revision_label": "v1"}).json()
    step = auth_client.post(
        f"/api/{slug}/workflows/{wf['id']}/revisions/{rev['id']}/steps",
        json={"step_type": "SCREENSHOT", "description": "shot"},
    ).json()
    auth_client.post(f"/api/{slug}/workflows/{wf['id']}/revisions/{rev['id']}/publish")

    suite = auth_client.post(f"/api/{slug}/suites", json={"name": "Timing Suite"}).json()
    suite_rev = auth_client.post(f"/api/{slug}/suites/{suite['id']}/revisions", json={"revision_label": "rv1"}).json()
    auth_client.post(
        f"/api/{slug}/revisions/{suite_rev['id']}/cases",
        json={"checkpoint_code": "TIME-001", "title": "c", "action_md": "a", "expected_result_md": "e"},
    )
    auth_client.post(f"/api/{slug}/suites/{suite['id']}/revisions/{suite_rev['id']}/publish")
    cycle = auth_client.post(
        f"/api/{slug}/cycles",
        json={"suite_id": suite["id"], "script_revision_id": suite_rev["id"], "name": "timing cycle", "environment": "test"},
    ).json()
    result_id = auth_client.get(f"/api/{slug}/cycles/{cycle['id']}/results").json()[0]["id"]

    queued = auth_client.post(
        f"/api/{slug}/workflow-runs", json={"workflow_revision_id": rev["id"], "cycle_test_result_id": result_id}
    ).json()
    run_id = queued["id"]
    token = _issue_runner_token(auth_client, "evidence-timing-runner")
    runner = _fresh_client()
    runner.headers.update({"X-Runner-Token": token})
    claim = runner.post(f"/api/{slug}/workflow-runs/claim").json()
    lease_token = claim["lease_token"]

    upload = runner.post(
        f"/api/{slug}/workflow-runs/{run_id}/evidence",
        params={"lease_token": lease_token},
        files={"file": ("shot.png", PNG_BYTES, "image/png")},
    )
    assert upload.status_code == 200, upload.text
    evidence_id = upload.json()["id"]

    report = auth_client.get(f"/api/{slug}/hybrid-reports/timing/runs/{run_id}").json()
    uploads = report["evidence_uploads"]
    assert len(uploads) == 1
    assert uploads[0]["evidence_id"] == evidence_id
    assert uploads[0]["upload_duration_ms"] is not None
    assert uploads[0]["upload_duration_ms"] >= 0


def test_checkpoint_waiting_and_resume_delay_timing(auth_client, project_slug):
    slug = project_slug
    wf = auth_client.post(f"/api/{slug}/workflows", json={"name": "cp timing wf"}).json()
    rev = auth_client.post(f"/api/{slug}/workflows/{wf['id']}/revisions", json={"revision_label": "v1"}).json()
    cp = auth_client.post(
        f"/api/{slug}/workflows/{wf['id']}/revisions/{rev['id']}/steps",
        json={"step_type": "MANUAL_CHECKPOINT", "description": "cp", "checkpoint_instructions": "check it"},
    ).json()
    post_step = auth_client.post(
        f"/api/{slug}/workflows/{wf['id']}/revisions/{rev['id']}/steps",
        json={"step_type": "SCREENSHOT", "description": "post"},
    ).json()
    auth_client.post(f"/api/{slug}/workflows/{wf['id']}/revisions/{rev['id']}/publish")

    queued = auth_client.post(f"/api/{slug}/workflow-runs", json={"workflow_revision_id": rev["id"]}).json()
    run_id = queued["id"]
    token = _issue_runner_token(auth_client, "cp-timing-runner")
    runner = _fresh_client()
    runner.headers.update({"X-Runner-Token": token})
    claim = runner.post(f"/api/{slug}/workflow-runs/claim").json()
    lease_token = claim["lease_token"]

    runner.post(f"/api/{slug}/workflow-runs/{run_id}/step-runs", json={"workflow_step_id": cp["id"], "lease_token": lease_token})
    runner.post(
        f"/api/{slug}/workflow-runs/{run_id}/events",
        json={"event_type": "CHECKPOINT_WAITING", "actor_type": "RUNNER", "lease_token": lease_token, "payload_json": f'{{"step_id":{cp["id"]}}}'},
    )
    time.sleep(0.05)

    decide = auth_client.post(
        f"/api/{slug}/workflow-runs/{run_id}/checkpoint-decision",
        json={"workflow_step_id": cp["id"], "status": "PASS", "actual_result_md": "ok"},
    )
    assert decide.status_code == 200, decide.text
    time.sleep(0.02)

    resume = runner.post(f"/api/{slug}/workflow-runs/{run_id}/checkpoint-resume", json={"workflow_step_id": cp["id"], "lease_token": lease_token})
    assert resume.status_code == 200, resume.text

    report = auth_client.get(f"/api/{slug}/hybrid-reports/timing/runs/{run_id}").json()
    assert len(report["checkpoints"]) == 1
    cp_timing = report["checkpoints"][0]
    assert cp_timing["workflow_step_id"] == cp["id"]
    assert cp_timing["checkpoint_waiting_duration_seconds"] >= 0.04
    assert cp_timing["human_decision_time_seconds"] == cp_timing["checkpoint_waiting_duration_seconds"]
    assert cp_timing["resume_delay_seconds"] >= 0.01


def test_step_and_run_duration_trend_across_multiple_runs(auth_client, project_slug):
    slug = project_slug
    wf_id, revision_id, step_ids = _make_published_workflow(auth_client, slug, name="trend wf", n_steps=1)
    run_1 = _run_to_completion(auth_client, slug, revision_id, step_ids, "trend-runner-1")
    run_2 = _run_to_completion(auth_client, slug, revision_id, step_ids, "trend-runner-2")

    step_trend = auth_client.get(
        f"/api/{slug}/hybrid-reports/timing/step-trend", params={"workflow_id": wf_id, "step_description": "timed step 0"}
    )
    assert step_trend.status_code == 200, step_trend.text
    trend_body = step_trend.json()
    assert [r["run_id"] for r in trend_body] == [run_1, run_2]
    for r in trend_body:
        assert r["duration_seconds"] is not None

    run_trend = auth_client.get(f"/api/{slug}/hybrid-reports/timing/run-trend", params={"workflow_id": wf_id})
    assert run_trend.status_code == 200
    assert [r["run_id"] for r in run_trend.json()] == [run_1, run_2]


def test_hybrid_dashboard_aggregates_reflect_real_runs(auth_client, project_slug):
    slug = project_slug
    wf_id, revision_id, step_ids = _make_published_workflow(auth_client, slug, name="dashboard wf", n_steps=1)
    run_id = _run_to_completion(auth_client, slug, revision_id, step_ids, "dashboard-runner")

    dashboard = auth_client.get(f"/api/{slug}/hybrid-reports/dashboard")
    assert dashboard.status_code == 200, dashboard.text
    body = dashboard.json()
    assert body["run_status_counts"]["PASSED"] >= 1
    assert body["provenance"]["machine_step_outcomes"]["PASSED"] >= 1
    assert set(body["provenance"]["human_checkpoint_decisions"].keys()) == {"PASS", "FAIL", "BLOCKED", "NOT_APPLICABLE"}
    reliability = body["runner_reliability"]
    assert any(r["total_runs_claimed"] >= 1 for r in reliability)
    assert body["runner_lost_frequency"]["total_terminal_runs"] >= 1
    assert body["retry_frequency"]["total_step_occurrences"] >= 1
    recent = body["recent_activity"]
    assert len(recent) > 0
    assert any(e["workflow_run_id"] == run_id for e in recent)

    failure_categories = auth_client.get(f"/api/{slug}/hybrid-reports/failure-categories")
    assert failure_categories.status_code == 200
    assert "LOCATOR_NOT_FOUND" in failure_categories.json()

    slowest = auth_client.get(f"/api/{slug}/hybrid-reports/slowest-steps")
    assert slowest.status_code == 200
    assert any(s["workflow_step_id"] == step_ids[0] for s in slowest.json())

    frequent_failures = auth_client.get(f"/api/{slug}/hybrid-reports/workflows-frequent-failures")
    assert frequent_failures.status_code == 200
    entry = next(e for e in frequent_failures.json() if e["workflow_id"] == wf_id)
    assert entry["total_terminal_runs"] >= 1
    assert entry["failed_runs"] == 0


def test_list_runs_status_filter_finds_stuck_queued_runs(auth_client, project_slug):
    """HYB-5 recovery tooling: an operator filters /workflow-runs?status=QUEUED
    to spot a run that's been waiting far longer than any runner should
    take to claim it (see docs/hybrid/RECOVERY_RUNBOOK.md)."""
    slug = project_slug
    _, revision_id, _ = _make_published_workflow(auth_client, slug, name="stuck queue wf", n_steps=1)
    queued = auth_client.post(f"/api/{slug}/workflow-runs", json={"workflow_revision_id": revision_id}).json()

    filtered = auth_client.get(f"/api/{slug}/workflow-runs", params={"status": "QUEUED"})
    assert filtered.status_code == 200
    assert any(r["id"] == queued["id"] for r in filtered.json())
    assert all(r["status"] == "QUEUED" for r in filtered.json())

    bad_status = auth_client.get(f"/api/{slug}/workflow-runs", params={"status": "NOT_A_REAL_STATUS"})
    assert bad_status.status_code == 400

    auth_client.post(f"/api/{slug}/workflow-runs/{queued['id']}/cancel")


def test_human_fail_is_never_counted_as_machine_outcome(auth_client, project_slug):
    """Provenance must stay structurally distinct: a human FAIL decision
    lands only in checkpoint_decision_counts, never in step_outcome_counts,
    however the dashboard aggregates them."""
    slug = project_slug
    wf = auth_client.post(f"/api/{slug}/workflows", json={"name": "provenance wf"}).json()
    rev = auth_client.post(f"/api/{slug}/workflows/{wf['id']}/revisions", json={"revision_label": "v1"}).json()
    cp = auth_client.post(
        f"/api/{slug}/workflows/{wf['id']}/revisions/{rev['id']}/steps",
        json={"step_type": "MANUAL_CHECKPOINT", "description": "cp", "checkpoint_instructions": "check"},
    ).json()
    auth_client.post(f"/api/{slug}/workflows/{wf['id']}/revisions/{rev['id']}/publish")

    queued = auth_client.post(f"/api/{slug}/workflow-runs", json={"workflow_revision_id": rev["id"]}).json()
    run_id = queued["id"]
    token = _issue_runner_token(auth_client, "provenance-runner")
    runner = _fresh_client()
    runner.headers.update({"X-Runner-Token": token})
    claim = runner.post(f"/api/{slug}/workflow-runs/claim").json()
    lease_token = claim["lease_token"]
    runner.post(f"/api/{slug}/workflow-runs/{run_id}/step-runs", json={"workflow_step_id": cp["id"], "lease_token": lease_token})
    runner.post(
        f"/api/{slug}/workflow-runs/{run_id}/events",
        json={"event_type": "CHECKPOINT_WAITING", "actor_type": "RUNNER", "lease_token": lease_token, "payload_json": f'{{"step_id":{cp["id"]}}}'},
    )
    fail = auth_client.post(
        f"/api/{slug}/workflow-runs/{run_id}/checkpoint-decision",
        json={"workflow_step_id": cp["id"], "status": "FAIL", "actual_result_md": "broken"},
    )
    assert fail.status_code == 200, fail.text

    dashboard = auth_client.get(f"/api/{slug}/hybrid-reports/dashboard").json()
    assert dashboard["provenance"]["human_checkpoint_decisions"]["FAIL"] >= 1
    # No automated STEP_RUN status is ever "FAIL" (only checkpoint decisions use that
    # exact vocabulary) -- WorkflowStepRun.status uses FAILED, kept in a disjoint set.
    assert "FAIL" not in dashboard["provenance"]["machine_step_outcomes"]

    # A racing second decision must not be able to override the terminal FAIL.
    conflict = auth_client.post(
        f"/api/{slug}/workflow-runs/{run_id}/checkpoint-decision",
        json={"workflow_step_id": cp["id"], "status": "PASS", "actual_result_md": "actually fine"},
    )
    assert conflict.status_code == 409
    run_after = auth_client.get(f"/api/{slug}/workflow-runs/{run_id}").json()
    assert run_after["status"] == "FAILED"
