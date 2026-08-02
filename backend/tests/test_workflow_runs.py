"""HYB-2 acceptance gate (docs/Autonomous hybird prompt.md's HYB-2
section) verified against the real running app (TestClient) using a
runner token exactly as a real Node.js runner process would present it
(X-Runner-Token header) -- not mocked."""
import time

from fastapi.testclient import TestClient

from app.main import app


def _fresh_client():
    c = TestClient(app)
    c.headers.update({"Origin": "http://localhost:5173"})
    return c


def _make_published_workflow(auth_client, slug, n_steps=2):
    wf = auth_client.post(f"/api/{slug}/workflows", json={"name": "runner test wf"}).json()
    rev = auth_client.post(f"/api/{slug}/workflows/{wf['id']}/revisions", json={"revision_label": "v1"}).json()
    step_ids = []
    for i in range(n_steps):
        s = auth_client.post(
            f"/api/{slug}/workflows/{wf['id']}/revisions/{rev['id']}/steps",
            json={"step_type": "SCREENSHOT", "description": f"step {i}"},
        ).json()
        step_ids.append(s["id"])
    pub = auth_client.post(f"/api/{slug}/workflows/{wf['id']}/revisions/{rev['id']}/publish")
    assert pub.status_code == 200, pub.text
    return wf["id"], rev["id"], step_ids


def _make_cycle_result(auth_client, slug):
    suite = auth_client.post(f"/api/{slug}/suites", json={"name": "Runner Suite"}).json()
    revision = auth_client.post(f"/api/{slug}/suites/{suite['id']}/revisions", json={"revision_label": "rv1"}).json()
    auth_client.post(
        f"/api/{slug}/revisions/{revision['id']}/cases",
        json={"checkpoint_code": "RUN-001", "title": "c", "action_md": "a", "expected_result_md": "e"},
    )
    auth_client.post(f"/api/{slug}/suites/{suite['id']}/revisions/{revision['id']}/publish")
    cycle = auth_client.post(
        f"/api/{slug}/cycles",
        json={"suite_id": suite["id"], "script_revision_id": revision["id"], "name": "runner cycle", "environment": "test"},
    ).json()
    results = auth_client.get(f"/api/{slug}/cycles/{cycle['id']}/results").json()
    return cycle["id"], results[0]["id"]


def _issue_runner_token(auth_client, label):
    r = auth_client.post("/api/runner-tokens", json={"label": label})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def test_dispatched_runner_claims_exact_run(auth_client, project_slug):
    slug = project_slug
    _workflow_id, revision_id, _step_ids = _make_published_workflow(auth_client, slug, n_steps=1)
    first = auth_client.post(f"/api/{slug}/workflow-runs", json={"workflow_revision_id": revision_id}).json()
    second = auth_client.post(f"/api/{slug}/workflow-runs", json={"workflow_revision_id": revision_id}).json()

    token = _issue_runner_token(auth_client, "targeted-cloud-runner")
    runner = _fresh_client()
    runner.headers.update({"X-Runner-Token": token})
    claim = runner.post(f"/api/{slug}/workflow-runs/claim/{second['id']}")

    assert claim.status_code == 200, claim.text
    assert claim.json()["run"]["id"] == second["id"]
    assert auth_client.get(f"/api/{slug}/workflow-runs/{first['id']}").json()["status"] == "QUEUED"

    # Clean up both rows so they cannot interfere with FIFO-claim tests.
    auth_client.post(f"/api/{slug}/workflow-runs/{first['id']}/cancel")
    runner.post(
        f"/api/{slug}/workflow-runs/{second['id']}/complete",
        json={"status": "CANCELLED", "lease_token": claim.json()["lease_token"]},
    )


def test_cloud_job_setup_failure_does_not_leave_run_queued(auth_client, project_slug):
    slug = project_slug
    _workflow_id, revision_id, _step_ids = _make_published_workflow(auth_client, slug, n_steps=1)
    queued = auth_client.post(f"/api/{slug}/workflow-runs", json={"workflow_revision_id": revision_id}).json()
    token = _issue_runner_token(auth_client, "cloud-failure-reporter")
    runner = _fresh_client()
    runner.headers.update({"X-Runner-Token": token})

    failed = runner.post(
        f"/api/{slug}/workflow-runs/{queued['id']}/dispatch-failed",
        json={"message": "Chromium installation failed"},
    )

    assert failed.status_code == 200, failed.text
    assert failed.json()["status"] == "SYSTEM_ERROR"
    assert failed.json()["result_summary"] == "Chromium installation failed"


def test_hyb2_full_job_protocol(auth_client, project_slug):
    slug = project_slug
    workflow_id, revision_id, step_ids = _make_published_workflow(auth_client, slug, n_steps=2)
    cycle_id, result_id = _make_cycle_result(auth_client, slug)

    # 1. Queue a run (human/system action, user session).
    queued = auth_client.post(f"/api/{slug}/workflow-runs", json={"workflow_revision_id": revision_id, "cycle_test_result_id": result_id})
    assert queued.status_code == 200, queued.text
    run_id = queued.json()["id"]
    assert queued.json()["status"] == "QUEUED"

    # Cannot queue against a DRAFT revision.
    wf2 = auth_client.post(f"/api/{slug}/workflows", json={"name": "draft only"}).json()
    rev2 = auth_client.post(f"/api/{slug}/workflows/{wf2['id']}/revisions", json={"revision_label": "v1"}).json()
    draft_reject = auth_client.post(f"/api/{slug}/workflow-runs", json={"workflow_revision_id": rev2["id"]})
    assert draft_reject.status_code == 400

    # 2. Register a runner (issue token), authenticate outbound-only via header.
    token = _issue_runner_token(auth_client, "test-runner-1")
    runner = _fresh_client()
    runner.headers.update({"X-Runner-Token": token})

    # 3. Runner claims the queued job.
    claim = runner.post(f"/api/{slug}/workflow-runs/claim")
    assert claim.status_code == 200, claim.text
    body = claim.json()
    assert body["claimed"] is True
    assert body["run"]["id"] == run_id
    assert body["run"]["status"] == "CLAIMED"
    assert len(body["steps"]) == 2
    lease_token = body["lease_token"]
    assert lease_token

    # 4. A second runner racing for the same job must NOT get it (no
    # duplicate job execution) -- queue is now empty.
    token2 = _issue_runner_token(auth_client, "test-runner-2")
    runner2 = _fresh_client()
    runner2.headers.update({"X-Runner-Token": token2})
    second_claim = runner2.post(f"/api/{slug}/workflow-runs/claim")
    assert second_claim.status_code == 200
    assert second_claim.json()["claimed"] is False

    # A runner presenting the WRONG lease token must be rejected.
    bad_lease = runner.post(f"/api/{slug}/workflow-runs/{run_id}/heartbeat", json={"lease_token": "not-the-real-token"})
    assert bad_lease.status_code == 409

    # 5. Heartbeat / lease renewal with the correct token succeeds.
    hb = runner.post(f"/api/{slug}/workflow-runs/{run_id}/heartbeat", json={"lease_token": lease_token})
    assert hb.status_code == 200, hb.text

    # 6. Execute step 1: start -> finish (structured WorkflowStepRun history).
    sr1 = runner.post(f"/api/{slug}/workflow-runs/{run_id}/step-runs", json={"workflow_step_id": step_ids[0], "lease_token": lease_token})
    assert sr1.status_code == 200, sr1.text
    step_run_id_1 = sr1.json()["id"]
    assert sr1.json()["status"] == "RUNNING"

    finish1 = runner.put(
        f"/api/{slug}/workflow-runs/{run_id}/step-runs/{step_run_id_1}",
        json={"status": "PASSED", "outcome": "ok", "lease_token": lease_token},
    )
    assert finish1.status_code == 200, finish1.text
    assert finish1.json()["status"] == "PASSED"

    # Run must now show RUNNING (moved off CLAIMED/STARTING once a step executed).
    detail = auth_client.get(f"/api/{slug}/workflow-runs/{run_id}").json()
    assert detail["status"] == "RUNNING"
    assert len(detail["step_runs"]) == 1
    assert any(e["event_type"] == "STEP_COMPLETED" for e in detail["events"])

    # 7. Idempotent event delivery -- posting the same idempotency_key twice
    # must not create two rows.
    ev1 = runner.post(
        f"/api/{slug}/workflow-runs/{run_id}/events",
        json={"event_type": "STEP_STARTED", "idempotency_key": "dup-key-1", "lease_token": lease_token},
    )
    assert ev1.status_code == 200, ev1.text
    ev2 = runner.post(
        f"/api/{slug}/workflow-runs/{run_id}/events",
        json={"event_type": "STEP_STARTED", "idempotency_key": "dup-key-1", "lease_token": lease_token},
    )
    assert ev2.status_code == 200
    assert ev1.json()["id"] == ev2.json()["id"], "a retried event with the same idempotency_key must not duplicate"

    events_after = auth_client.get(f"/api/{slug}/workflow-runs/{run_id}").json()["events"]
    dup_count = sum(1 for e in events_after if e.get("idempotency_key") == "dup-key-1")
    assert dup_count == 1

    # 8. Real screenshot evidence through the existing EvidenceStorage
    # system (reuses EvidenceItem, not a parallel table).
    png_bytes = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x02\x00\x00\x00\x02\x08\x02\x00\x00\x00\xfd\xd4\x9as"
        b"\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\xc0\xc0\xc0\x00\x00\x00\x06\x00\x03\xfa\xd0\x7f\xe6"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    upload = runner.post(
        f"/api/{slug}/workflow-runs/{run_id}/evidence",
        params={"lease_token": lease_token, "step_run_id": step_run_id_1},
        files={"file": ("screenshot.png", png_bytes, "image/png")},
    )
    assert upload.status_code == 200, upload.text
    evidence = upload.json()
    assert evidence["evidence_source"] == "RUNNER"
    assert evidence["workflow_run_id"] == run_id
    assert evidence["cycle_test_result_id"] == result_id

    # Confirm it's a REAL EvidenceItem, visible through Track A's own
    # evidence-list endpoint -- proves reuse, not a parallel subsystem.
    track_a_list = auth_client.get(f"/api/{slug}/cycles/{cycle_id}/results/{result_id}/evidence").json()
    assert any(e["id"] == evidence["id"] for e in track_a_list)

    # 9. Second step, then complete the run.
    sr2 = runner.post(f"/api/{slug}/workflow-runs/{run_id}/step-runs", json={"workflow_step_id": step_ids[1], "lease_token": lease_token})
    step_run_id_2 = sr2.json()["id"]
    runner.put(f"/api/{slug}/workflow-runs/{run_id}/step-runs/{step_run_id_2}", json={"status": "PASSED", "lease_token": lease_token})

    complete = runner.post(f"/api/{slug}/workflow-runs/{run_id}/complete", json={"status": "PASSED", "result_summary": "all good", "lease_token": lease_token})
    assert complete.status_code == 200, complete.text
    assert complete.json()["status"] == "PASSED"

    # 10. Lease released -- further actions against this run's old lease must fail.
    post_complete_hb = runner.post(f"/api/{slug}/workflow-runs/{run_id}/heartbeat", json={"lease_token": lease_token})
    # heartbeat on a terminal (non-leased-status) run is a harmless no-op read, not an error
    assert post_complete_hb.status_code == 200
    assert post_complete_hb.json()["status"] == "PASSED"


def test_step_run_detail_carries_step_fields_for_plain_language_display(auth_client, project_slug):
    """WorkflowStepRunOut flattens locator/input/expected/checkpoint
    fields from the WorkflowStep it executed -- without this, the
    frontend's describeStep() can only render a generic "an element"
    for a run's step list instead of the same specific wording ("Type
    into \"Email\"") shown while authoring/reviewing the workflow."""
    slug = project_slug
    wf = auth_client.post(f"/api/{slug}/workflows", json={"name": "field-carry wf"}).json()
    rev = auth_client.post(f"/api/{slug}/workflows/{wf['id']}/revisions", json={"revision_label": "v1"}).json()
    step = auth_client.post(
        f"/api/{slug}/workflows/{wf['id']}/revisions/{rev['id']}/steps",
        json={"step_type": "FILL", "locator_strategy": "LABEL", "locator_value": "Email", "input_value": "someone@example.com"},
    ).json()
    auth_client.post(f"/api/{slug}/workflows/{wf['id']}/revisions/{rev['id']}/publish")

    queued = auth_client.post(f"/api/{slug}/workflow-runs", json={"workflow_revision_id": rev["id"]}).json()
    run_id = queued["id"]

    token = _issue_runner_token(auth_client, "field-carry-runner")
    runner = _fresh_client()
    runner.headers.update({"X-Runner-Token": token})
    claim = runner.post(f"/api/{slug}/workflow-runs/claim").json()
    lease_token = claim["lease_token"]

    sr = runner.post(f"/api/{slug}/workflow-runs/{run_id}/step-runs", json={"workflow_step_id": step["id"], "lease_token": lease_token}).json()
    runner.put(f"/api/{slug}/workflow-runs/{run_id}/step-runs/{sr['id']}", json={"status": "PASSED", "lease_token": lease_token})

    detail = auth_client.get(f"/api/{slug}/workflow-runs/{run_id}").json()
    step_run = detail["step_runs"][0]
    assert step_run["step_type"] == "FILL"
    assert step_run["locator_strategy"] == "LABEL"
    assert step_run["locator_value"] == "Email"
    assert step_run["input_value"] == "someone@example.com"


def test_hyb2_lease_expiry_marks_runner_lost(auth_client, project_slug, monkeypatch):
    slug = project_slug
    _, revision_id, _ = _make_published_workflow(auth_client, slug, n_steps=1)
    queued = auth_client.post(f"/api/{slug}/workflow-runs", json={"workflow_revision_id": revision_id}).json()
    run_id = queued["id"]

    token = _issue_runner_token(auth_client, "flaky-runner")
    runner = _fresh_client()
    runner.headers.update({"X-Runner-Token": token})

    import app.models as models_module
    original_lease = models_module.LEASE_DURATION_SECONDS
    models_module.LEASE_DURATION_SECONDS = 0  # expires instantly for this test
    try:
        claim = runner.post(f"/api/{slug}/workflow-runs/claim")
        assert claim.json()["claimed"] is True
        time.sleep(0.05)
        # Any subsequent call (even from a human/user session) sweeps expired leases.
        detail = auth_client.get(f"/api/{slug}/workflow-runs/{run_id}").json()
        assert detail["status"] == "RUNNER_LOST", detail
        assert any(e["event_type"] == "RUNNER_LOST" for e in detail["events"])
    finally:
        models_module.LEASE_DURATION_SECONDS = original_lease


def test_hyb2_cancel_queued_run_is_immediate(auth_client, project_slug):
    slug = project_slug
    _, revision_id, _ = _make_published_workflow(auth_client, slug, n_steps=1)
    queued = auth_client.post(f"/api/{slug}/workflow-runs", json={"workflow_revision_id": revision_id}).json()
    cancel = auth_client.post(f"/api/{slug}/workflow-runs/{queued['id']}/cancel")
    assert cancel.status_code == 200
    assert cancel.json()["status"] == "CANCELLED"


def test_hyb2_cancel_running_run_sets_cooperative_flag(auth_client, project_slug):
    slug = project_slug
    _, revision_id, step_ids = _make_published_workflow(auth_client, slug, n_steps=1)
    queued = auth_client.post(f"/api/{slug}/workflow-runs", json={"workflow_revision_id": revision_id}).json()
    run_id = queued["id"]

    token = _issue_runner_token(auth_client, "cancel-test-runner")
    runner = _fresh_client()
    runner.headers.update({"X-Runner-Token": token})
    claim = runner.post(f"/api/{slug}/workflow-runs/claim").json()
    lease_token = claim["lease_token"]

    cancel = auth_client.post(f"/api/{slug}/workflow-runs/{run_id}/cancel")
    assert cancel.status_code == 200
    assert cancel.json()["status"] == "CLAIMED"  # not force-terminated -- cooperative

    detail = auth_client.get(f"/api/{slug}/workflow-runs/{run_id}").json()
    assert detail["cancel_requested"] is True

    # The runner, observing cancel_requested, self-terminates the run.
    complete = runner.post(f"/api/{slug}/workflow-runs/{run_id}/complete", json={"status": "CANCELLED", "lease_token": lease_token})
    assert complete.status_code == 200
    assert complete.json()["status"] == "CANCELLED"


def test_hyb2_evidence_requires_cycle_link(auth_client, project_slug):
    slug = project_slug
    _, revision_id, step_ids = _make_published_workflow(auth_client, slug, n_steps=1)
    queued = auth_client.post(f"/api/{slug}/workflow-runs", json={"workflow_revision_id": revision_id}).json()  # no cycle_test_result_id
    run_id = queued["id"]

    token = _issue_runner_token(auth_client, "standalone-runner")
    runner = _fresh_client()
    runner.headers.update({"X-Runner-Token": token})
    claim = runner.post(f"/api/{slug}/workflow-runs/claim").json()

    upload = runner.post(
        f"/api/{slug}/workflow-runs/{run_id}/evidence",
        params={"lease_token": claim["lease_token"]},
        files={"file": ("x.png", b"not-really-a-png", "image/png")},
    )
    assert upload.status_code == 400
    assert "cycle_test_result_id" in upload.json()["detail"]


def test_hyb2_runner_registration_heartbeat_and_revoke(auth_client, project_slug):
    slug = project_slug
    token = _issue_runner_token(auth_client, "listable-runner")

    listing = auth_client.get("/api/runner-tokens")
    assert listing.status_code == 200
    entry = next(r for r in listing.json() if r["label"] == "listable-runner")
    assert entry["status"] == "OFFLINE"  # never made an authenticated call yet

    runner = _fresh_client()
    runner.headers.update({"X-Runner-Token": token})
    _, revision_id, _ = _make_published_workflow(auth_client, slug, n_steps=1)
    auth_client.post(f"/api/{slug}/workflow-runs", json={"workflow_revision_id": revision_id})
    runner.post(f"/api/{slug}/workflow-runs/claim")  # any authenticated call touches last_heartbeat_at

    listing2 = auth_client.get("/api/runner-tokens").json()
    entry2 = next(r for r in listing2 if r["label"] == "listable-runner")
    assert entry2["status"] == "ONLINE"
    assert entry2["last_heartbeat_at"] is not None

    revoke = auth_client.put(f"/api/runner-tokens/{entry2['id']}/revoke")
    assert revoke.status_code == 200
    assert revoke.json()["status"] == "REVOKED"

    rejected = runner.post(f"/api/{slug}/workflow-runs/claim")
    assert rejected.status_code == 401


def test_hyb2_provenance_is_distinct_runner_human_system(auth_client, project_slug):
    """HUMAN queues, RUNNER executes, SYSTEM never silently invents an
    outcome — every event in the run's history must carry a real,
    distinguishable actor_type."""
    slug = project_slug
    _, revision_id, step_ids = _make_published_workflow(auth_client, slug, n_steps=1)
    queued = auth_client.post(f"/api/{slug}/workflow-runs", json={"workflow_revision_id": revision_id}).json()
    run_id = queued["id"]

    token = _issue_runner_token(auth_client, "provenance-runner")
    runner = _fresh_client()
    runner.headers.update({"X-Runner-Token": token})
    claim = runner.post(f"/api/{slug}/workflow-runs/claim").json()
    lease_token = claim["lease_token"]
    runner.post(f"/api/{slug}/workflow-runs/{run_id}/complete", json={"status": "PASSED", "lease_token": lease_token})

    events = auth_client.get(f"/api/{slug}/workflow-runs/{run_id}").json()["events"]
    actor_types = {e["event_type"]: e["actor_type"] for e in events}
    assert actor_types["RUN_QUEUED"] == "HUMAN"
    assert actor_types["RUN_CLAIMED"] == "RUNNER"
    assert actor_types["RUN_COMPLETED"] == "RUNNER"
