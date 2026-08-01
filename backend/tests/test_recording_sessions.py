"""HYB-3 acceptance gate (backend protocol layer) -- verified against
the real running app (TestClient) using a runner token exactly as the
real Node.js recorder would present it. Real headed-browser recording
verification is separate (see the session's manual verification
record in docs/hybrid/SESSION_HANDOFF.md); this file locks in the
claim/lease/append/review/save-as-draft protocol itself."""
from fastapi.testclient import TestClient

from app.main import app


def _fresh_client():
    c = TestClient(app)
    c.headers.update({"Origin": "http://localhost:5173"})
    return c


def _issue_runner_token(auth_client, label):
    r = auth_client.post("/api/runner-tokens", json={"label": label})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _make_workflow(auth_client, slug, name="recorder test wf"):
    wf = auth_client.post(f"/api/{slug}/workflows", json={"name": name})
    assert wf.status_code == 200, wf.text
    return wf.json()["id"]


def test_hyb3_full_recording_protocol(auth_client, project_slug):
    slug = project_slug
    workflow_id = _make_workflow(auth_client, slug)

    # 1. Tester requests a recording session.
    created = auth_client.post(f"/api/{slug}/recording-sessions", json={"workflow_id": workflow_id, "target_url": "http://localhost:5173/login"})
    assert created.status_code == 200, created.text
    session_id = created.json()["id"]
    assert created.json()["status"] == "REQUESTED"

    # 2. Runner claims it (outbound-only).
    token = _issue_runner_token(auth_client, "recorder-runner-1")
    runner = _fresh_client()
    runner.headers.update({"X-Runner-Token": token})
    claim = runner.post(f"/api/{slug}/recording-sessions/claim")
    assert claim.status_code == 200, claim.text
    body = claim.json()
    assert body["claimed"] is True
    lease_token = body["lease_token"]

    # A second runner racing for the same session gets nothing.
    token2 = _issue_runner_token(auth_client, "recorder-runner-2")
    runner2 = _fresh_client()
    runner2.headers.update({"X-Runner-Token": token2})
    second = runner2.post(f"/api/{slug}/recording-sessions/claim")
    assert second.json()["claimed"] is False

    # 3. Runner confirms the browser is actually up -> RECORDING.
    started = runner.post(f"/api/{slug}/recording-sessions/{session_id}/recording-started", params={"lease_token": lease_token})
    assert started.status_code == 200, started.text
    assert started.json()["status"] == "RECORDING"

    # 4. Runner appends captured steps as the tester interacts with the browser.
    nav = runner.post(
        f"/api/{slug}/recording-sessions/{session_id}/steps",
        json={"step_type": "NAVIGATE", "input_value": "http://localhost:5173/login", "page_context": "/login", "lease_token": lease_token},
    )
    assert nav.status_code == 200, nav.text

    fill = runner.post(
        f"/api/{slug}/recording-sessions/{session_id}/steps",
        json={
            "step_type": "FILL", "locator_strategy": "LABEL", "locator_value": "Email",
            "input_value": "tester@example.com", "page_context": "/login", "lease_token": lease_token,
        },
    )
    assert fill.status_code == 200

    # A sensitive step must NEVER carry a real value -- backend rejects
    # it outright if the runner ever tried to send one.
    bad_sensitive = runner.post(
        f"/api/{slug}/recording-sessions/{session_id}/steps",
        json={
            "step_type": "FILL", "locator_strategy": "LABEL", "locator_value": "Password",
            "input_value": "hunter2", "is_sensitive": True, "lease_token": lease_token,
        },
    )
    assert bad_sensitive.status_code == 400
    assert "sensitive" in bad_sensitive.json()["detail"].lower()

    # The real recorder never sends a value for a sensitive field at all.
    sensitive = runner.post(
        f"/api/{slug}/recording-sessions/{session_id}/steps",
        json={
            "step_type": "FILL", "locator_strategy": "LABEL", "locator_value": "Password",
            "is_sensitive": True, "page_context": "/login", "lease_token": lease_token,
        },
    )
    assert sensitive.status_code == 200
    assert sensitive.json()["input_value"] is None
    assert sensitive.json()["is_sensitive"] is True

    click = runner.post(
        f"/api/{slug}/recording-sessions/{session_id}/steps",
        json={"step_type": "CLICK", "locator_strategy": "ROLE", "locator_value": "button:Sign in", "lease_token": lease_token},
    )
    assert click.status_code == 200

    # Manual checkpoint the tester inserted mid-recording.
    checkpoint = runner.post(
        f"/api/{slug}/recording-sessions/{session_id}/steps",
        json={"step_type": "MANUAL_CHECKPOINT", "checkpoint_instructions": "Confirm dashboard looks right", "lease_token": lease_token},
    )
    assert checkpoint.status_code == 200
    checkpoint_step_id = checkpoint.json()["id"]

    # An uncertain simplification -- flagged for review, not silently applied.
    flagged = runner.post(
        f"/api/{slug}/recording-sessions/{session_id}/steps",
        json={
            "step_type": "CLICK", "locator_strategy": "CSS", "locator_value": "div.card:nth-child(3)",
            "needs_review": True, "review_note": "no stable text or test id found -- CSS fallback used", "lease_token": lease_token,
        },
    )
    assert flagged.status_code == 200
    assert flagged.json()["needs_review"] is True

    # 5. Heartbeat / lease renewal.
    hb = runner.post(f"/api/{slug}/recording-sessions/{session_id}/heartbeat", json={"lease_token": lease_token})
    assert hb.status_code == 200

    # 6. Wrong lease token must be rejected.
    bad_lease = runner.post(f"/api/{slug}/recording-sessions/{session_id}/heartbeat", json={"lease_token": "wrong"})
    assert bad_lease.status_code == 409

    # 7. Locator testing -- tester requests, runner (still polling) answers
    # with the exact same resolveLocator() code path replay uses.
    test_req = auth_client.post(f"/api/{slug}/recording-sessions/{session_id}/steps/{click.json()['id']}/test-locator")
    assert test_req.status_code == 200
    assert test_req.json()["locator_test_requested"] is True

    pending = runner.get(f"/api/{slug}/recording-sessions/{session_id}/pending-locator-tests", params={"lease_token": lease_token})
    assert pending.status_code == 200
    assert len(pending.json()) == 1
    assert pending.json()[0]["id"] == click.json()["id"]

    result = runner.post(
        f"/api/{slug}/recording-sessions/{session_id}/steps/{click.json()['id']}/locator-test-result",
        json={"matched_count": 1, "ok": True, "lease_token": lease_token},
    )
    assert result.status_code == 200
    assert result.json()["locator_test_requested"] is False
    assert "matched_count" in result.json()["locator_test_result_json"]

    # 8. Tester pauses (browser stays alive, listener gates on a paused flag runner-side).
    paused = auth_client.post(f"/api/{slug}/recording-sessions/{session_id}/pause")
    assert paused.status_code == 200
    assert paused.json()["status"] == "PAUSED"

    # Cannot append while paused.
    blocked = runner.post(
        f"/api/{slug}/recording-sessions/{session_id}/steps",
        json={"step_type": "SCREENSHOT", "lease_token": lease_token},
    )
    assert blocked.status_code == 400

    resumed = auth_client.post(f"/api/{slug}/recording-sessions/{session_id}/resume")
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "RECORDING"

    screenshot = runner.post(
        f"/api/{slug}/recording-sessions/{session_id}/steps",
        json={"step_type": "SCREENSHOT", "lease_token": lease_token},
    )
    assert screenshot.status_code == 200

    # 9. Tester stops recording.
    stopped = auth_client.post(f"/api/{slug}/recording-sessions/{session_id}/stop")
    assert stopped.status_code == 200
    assert stopped.json()["status"] == "STOPPED"

    # 10. Review: edit a flagged step, delete another, reorder.
    detail_before = auth_client.get(f"/api/{slug}/recording-sessions/{session_id}").json()
    all_ids = [s["id"] for s in detail_before["recorded_steps"]]

    edited = auth_client.put(
        f"/api/{slug}/recording-sessions/{session_id}/steps/{flagged.json()['id']}",
        json={"locator_strategy": "TEXT", "locator_value": "Third card", "needs_review": False},
    )
    assert edited.status_code == 200
    assert edited.json()["needs_review"] is False  # explicit edit resolves the flag

    deleted = auth_client.delete(f"/api/{slug}/recording-sessions/{session_id}/steps/{checkpoint_step_id}")
    assert deleted.status_code == 200
    remaining_ids = [i for i in all_ids if i != checkpoint_step_id]

    reordered = auth_client.post(f"/api/{slug}/recording-sessions/{session_id}/steps/reorder", json={"step_ids_in_order": list(reversed(remaining_ids))})
    assert reordered.status_code == 200
    assert [s["id"] for s in reordered.json()] == list(reversed(remaining_ids))

    # The recorder deliberately never invents a variable name for a
    # sensitive field -- the tester assigns one during review, same as
    # a manually-authored step would require (HYB-1's own validation).
    name_the_secret = auth_client.put(
        f"/api/{slug}/recording-sessions/{session_id}/steps/{sensitive.json()['id']}",
        json={"input_value": "${SECRET_LOGIN_PASSWORD}"},
    )
    assert name_the_secret.status_code == 200
    assert name_the_secret.json()["input_value"] == "${SECRET_LOGIN_PASSWORD}"

    # 11. Save as DRAFT -- never auto-published.
    saved = auth_client.post(f"/api/{slug}/recording-sessions/{session_id}/save-as-draft", json={"revision_label": "recorded-v1"})
    assert saved.status_code == 200, saved.text
    assert saved.json()["status"] == "DRAFT"
    revision_id = saved.json()["id"]

    steps_in_new_revision = auth_client.get(f"/api/{slug}/workflows/{workflow_id}/revisions/{revision_id}/steps").json()
    assert len(steps_in_new_revision) == len(remaining_ids)
    assert any(
        s["step_type"] == "FILL" and s["is_sensitive"] and s["input_value"] == "${SECRET_LOGIN_PASSWORD}"
        for s in steps_in_new_revision
    ), "the sensitive step's real value must never appear -- only the placeholder the tester assigned during review"
    assert all(s["locator_source"] == "RECORDER" for s in steps_in_new_revision if s["locator_strategy"])

    session_after = auth_client.get(f"/api/{slug}/recording-sessions/{session_id}").json()
    assert session_after["status"] == "SAVED"

    # The saved draft can now be published exactly like any other draft (HYB-1).
    published = auth_client.post(f"/api/{slug}/workflows/{workflow_id}/revisions/{revision_id}/publish")
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "PUBLISHED"


def test_hyb3_discard_wipes_recorded_steps(auth_client, project_slug):
    slug = project_slug
    workflow_id = _make_workflow(auth_client, slug, "discard test wf")
    created = auth_client.post(f"/api/{slug}/recording-sessions", json={"workflow_id": workflow_id, "target_url": "http://localhost:5173/login"}).json()
    session_id = created["id"]

    token = _issue_runner_token(auth_client, "discard-runner")
    runner = _fresh_client()
    runner.headers.update({"X-Runner-Token": token})
    claim = runner.post(f"/api/{slug}/recording-sessions/claim").json()
    lease_token = claim["lease_token"]
    runner.post(f"/api/{slug}/recording-sessions/{session_id}/recording-started", params={"lease_token": lease_token})
    runner.post(f"/api/{slug}/recording-sessions/{session_id}/steps", json={"step_type": "SCREENSHOT", "lease_token": lease_token})

    discarded = auth_client.post(f"/api/{slug}/recording-sessions/{session_id}/discard")
    assert discarded.status_code == 200
    assert discarded.json()["status"] == "DISCARDED"

    detail = auth_client.get(f"/api/{slug}/recording-sessions/{session_id}").json()
    assert detail["recorded_steps"] == []


def test_hyb3_lease_expiry_marks_runner_lost(auth_client, project_slug):
    slug = project_slug
    workflow_id = _make_workflow(auth_client, slug, "expiry test wf")
    created = auth_client.post(f"/api/{slug}/recording-sessions", json={"workflow_id": workflow_id, "target_url": "http://localhost:5173/login"}).json()
    session_id = created["id"]

    token = _issue_runner_token(auth_client, "flaky-recorder-runner")
    runner = _fresh_client()
    runner.headers.update({"X-Runner-Token": token})

    import app.routers.recording_sessions as rs_module
    original = rs_module.LEASE_DURATION_SECONDS
    rs_module.LEASE_DURATION_SECONDS = 0
    try:
        claim = runner.post(f"/api/{slug}/recording-sessions/claim").json()
        assert claim["claimed"] is True
        import time
        time.sleep(0.05)
        detail = auth_client.get(f"/api/{slug}/recording-sessions/{session_id}").json()
        assert detail["status"] == "RUNNER_LOST"
    finally:
        rs_module.LEASE_DURATION_SECONDS = original


def test_hyb3_cannot_save_non_stopped_session(auth_client, project_slug):
    slug = project_slug
    workflow_id = _make_workflow(auth_client, slug, "not stopped wf")
    created = auth_client.post(f"/api/{slug}/recording-sessions", json={"workflow_id": workflow_id, "target_url": "http://localhost:5173/login"}).json()
    r = auth_client.post(f"/api/{slug}/recording-sessions/{created['id']}/save-as-draft", json={"revision_label": "x"})
    assert r.status_code == 400


def test_hyb3_authorization_boundaries(auth_client, project_slug):
    slug = project_slug
    workflow_id = _make_workflow(auth_client, slug, "authz wf")

    viewer_created = auth_client.post("/api/auth/users", json={"email": "rec-viewer@example.com", "password": "ViewerPass123!", "role": "VIEWER"})
    assert viewer_created.status_code == 200
    viewer = _fresh_client()
    viewer.post("/api/auth/login", json={"email": "rec-viewer@example.com", "password": "ViewerPass123!"})
    viewer.post("/api/auth/change-password", json={"current_password": "ViewerPass123!", "new_password": "ViewerPass456!"})

    viewer_create = viewer.post(f"/api/{slug}/recording-sessions", json={"workflow_id": workflow_id, "target_url": "http://localhost:5173/login"})
    assert viewer_create.status_code == 403

    viewer_read = viewer.get(f"/api/{slug}/recording-sessions")
    assert viewer_read.status_code == 200  # VIEWER can read
