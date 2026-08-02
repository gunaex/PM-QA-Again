"""ADR-HYB-002 acceptance gate: Chrome extension recording mode,
verified against the real running app (TestClient). The extension
itself is JavaScript (see extension/), so this file exercises the
backend protocol it drives -- the exact same way the real extension's
background service worker would call these endpoints: a short-lived,
recording-session-scoped token, never a runner token, never the
tester's own JWT."""
import base64
import json
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from app.main import app


def _fresh_client():
    c = TestClient(app)
    c.headers.update({"Origin": "http://localhost:5173"})
    return c


def _make_workflow(auth_client, slug, name="ext recorder wf"):
    wf = auth_client.post(f"/api/{slug}/workflows", json={"name": name})
    assert wf.status_code == 200, wf.text
    return wf.json()["id"]


def _create_and_authorize(auth_client, slug, workflow_id):
    created = auth_client.post(f"/api/{slug}/recording-sessions", json={"workflow_id": workflow_id, "target_url": "http://localhost:5173/login"}).json()
    session_id = created["id"]
    auth = auth_client.post(f"/api/{slug}/recording-sessions/{session_id}/authorize-extension")
    assert auth.status_code == 200, auth.text
    return session_id, auth.json()["token"]


def test_extension_full_recording_protocol(auth_client, project_slug):
    slug = project_slug
    workflow_id = _make_workflow(auth_client, slug)
    session_id, ext_token = _create_and_authorize(auth_client, slug, workflow_id)

    # The extension itself never authenticates as a "user" or a
    # "runner" -- a bare client presenting only the extension token.
    ext = _fresh_client()

    connect = ext.post(f"/api/{slug}/recording-sessions/{session_id}/extension-connect", json={"extension_token": ext_token})
    assert connect.status_code == 200, connect.text
    assert connect.json()["status"] == "RECORDING"

    nav = ext.post(
        f"/api/{slug}/recording-sessions/{session_id}/steps",
        json={"step_type": "NAVIGATE", "input_value": "http://localhost:5173/login", "page_context": "/login", "extension_token": ext_token},
    )
    assert nav.status_code == 200, nav.text

    fill = ext.post(
        f"/api/{slug}/recording-sessions/{session_id}/steps",
        json={"step_type": "FILL", "locator_strategy": "LABEL", "locator_value": "Email", "input_value": "tester@example.com", "extension_token": ext_token},
    )
    assert fill.status_code == 200

    # Sensitive field redaction -- the content script must never send a
    # real value; the backend also rejects one outright if it ever did.
    bad_sensitive = ext.post(
        f"/api/{slug}/recording-sessions/{session_id}/steps",
        json={"step_type": "FILL", "locator_strategy": "LABEL", "locator_value": "Password", "input_value": "hunter2", "is_sensitive": True, "extension_token": ext_token},
    )
    assert bad_sensitive.status_code == 400

    sensitive = ext.post(
        f"/api/{slug}/recording-sessions/{session_id}/steps",
        json={"step_type": "FILL", "locator_strategy": "LABEL", "locator_value": "Password", "is_sensitive": True, "extension_token": ext_token},
    )
    assert sensitive.status_code == 200
    assert sensitive.json()["input_value"] is None

    click = ext.post(
        f"/api/{slug}/recording-sessions/{session_id}/steps",
        json={"step_type": "CLICK", "locator_strategy": "ROLE", "locator_value": "button:Sign in", "extension_token": ext_token},
    )
    assert click.status_code == 200

    # Heartbeat renews the extension's own authorization (not a runner lease).
    hb = ext.post(f"/api/{slug}/recording-sessions/{session_id}/heartbeat", json={"extension_token": ext_token})
    assert hb.status_code == 200

    # Pause/resume/undo/stop -- callable via the extension's own token,
    # never the tester's JWT.
    paused = ext.post(f"/api/{slug}/recording-sessions/{session_id}/pause", params={"extension_token": ext_token})
    assert paused.status_code == 200
    assert paused.json()["status"] == "PAUSED"

    resumed = ext.post(f"/api/{slug}/recording-sessions/{session_id}/resume", params={"extension_token": ext_token})
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "RECORDING"

    undo = ext.post(f"/api/{slug}/recording-sessions/{session_id}/undo-last-step", params={"extension_token": ext_token})
    assert undo.status_code == 200
    remaining_types = [s["step_type"] for s in undo.json()["recorded_steps"]]
    assert "CLICK" not in remaining_types  # the last-appended step (click) was undone

    # Undo again, again, until back at the start.
    for _ in range(3):
        ext.post(f"/api/{slug}/recording-sessions/{session_id}/undo-last-step", params={"extension_token": ext_token})
    empty = ext.post(f"/api/{slug}/recording-sessions/{session_id}/undo-last-step", params={"extension_token": ext_token})
    assert empty.status_code == 400
    assert "no recorded steps" in empty.json()["detail"].lower()

    # Re-append enough steps to save a real draft.
    ext.post(f"/api/{slug}/recording-sessions/{session_id}/steps", json={"step_type": "SCREENSHOT", "extension_token": ext_token})

    stopped = ext.post(f"/api/{slug}/recording-sessions/{session_id}/stop", params={"extension_token": ext_token})
    assert stopped.status_code == 200
    assert stopped.json()["status"] == "STOPPED"

    # Extension token is revoked immediately on stop. Heartbeat on a
    # terminal-status session is a harmless no-op read (matches the
    # existing precedent for runner-mode heartbeats against a completed
    # workflow run) -- but any real mutating call must reject the
    # revoked token outright.
    reuse_attempt = ext.post(
        f"/api/{slug}/recording-sessions/{session_id}/steps",
        json={"step_type": "SCREENSHOT", "extension_token": ext_token},
    )
    assert reuse_attempt.status_code == 401

    # Human review + save-as-draft + publish -- completely unchanged code path.
    saved = auth_client.post(f"/api/{slug}/recording-sessions/{session_id}/save-as-draft", json={"revision_label": "ext-v1"})
    assert saved.status_code == 200, saved.text
    assert saved.json()["status"] == "DRAFT"
    published = auth_client.post(f"/api/{slug}/workflows/{workflow_id}/revisions/{saved.json()['id']}/publish")
    assert published.status_code == 200
    assert published.json()["status"] == "PUBLISHED"


def test_extension_token_is_scoped_to_its_own_session_only(auth_client, project_slug):
    slug = project_slug
    workflow_id = _make_workflow(auth_client, slug, "scoping wf")
    session_id_a, token_a = _create_and_authorize(auth_client, slug, workflow_id)
    session_id_b, _token_b = _create_and_authorize(auth_client, slug, workflow_id)

    ext = _fresh_client()
    # token_a must not authorize connecting to session B.
    cross = ext.post(f"/api/{slug}/recording-sessions/{session_id_b}/extension-connect", json={"extension_token": token_a})
    assert cross.status_code == 401

    # Clean up -- both sessions would otherwise stay REQUESTED forever
    # and get picked up by a later, unrelated test's /claim (FIFO across
    # this whole shared session-scoped project).
    auth_client.post(f"/api/{slug}/recording-sessions/{session_id_a}/discard")
    auth_client.post(f"/api/{slug}/recording-sessions/{session_id_b}/discard")


def test_authorize_extension_returns_a_working_pairing_code(auth_client, project_slug):
    """The popup's one-paste path: pairing_code is base64 JSON bundling
    exactly the four fields the Advanced manual-entry fields require,
    and the token embedded in it is the same real, working token
    returned alongside it (not a decoy) -- decoding it and using it to
    connect must succeed exactly like the plain `token` field does."""
    slug = project_slug
    workflow_id = _make_workflow(auth_client, slug, "pairing code wf")
    created = auth_client.post(f"/api/{slug}/recording-sessions", json={"workflow_id": workflow_id, "target_url": "http://localhost:5173/login"}).json()
    session_id = created["id"]

    auth = auth_client.post(f"/api/{slug}/recording-sessions/{session_id}/authorize-extension")
    assert auth.status_code == 200, auth.text
    body = auth.json()
    assert "pairing_code" in body and body["pairing_code"]

    decoded = json.loads(base64.b64decode(body["pairing_code"]))
    assert decoded["projectSlug"] == slug
    assert decoded["sessionId"] == session_id
    assert decoded["token"] == body["token"]
    assert decoded["backendUrl"].startswith("http")

    # The decoded token is the real thing, not a placeholder -- prove it
    # by actually connecting with it, exactly as the popup would after
    # decoding the pasted pairing code.
    ext = _fresh_client()
    connect = ext.post(f"/api/{slug}/recording-sessions/{session_id}/extension-connect", json={"extension_token": decoded["token"]})
    assert connect.status_code == 200, connect.text
    assert connect.json()["status"] == "RECORDING"


def test_extension_authorization_only_mintable_once_requested(auth_client, project_slug):
    slug = project_slug
    workflow_id = _make_workflow(auth_client, slug, "double auth wf")
    session_id, token = _create_and_authorize(auth_client, slug, workflow_id)
    ext = _fresh_client()
    ext.post(f"/api/{slug}/recording-sessions/{session_id}/extension-connect", json={"extension_token": token})

    # Session is now RECORDING, not REQUESTED -- a second authorize call
    # (e.g. an accidental double-click) must be rejected, not silently
    # mint a second live credential for an already-connected session.
    second_auth = auth_client.post(f"/api/{slug}/recording-sessions/{session_id}/authorize-extension")
    assert second_auth.status_code == 400


def test_extension_missing_or_garbage_token_is_rejected(auth_client, project_slug):
    slug = project_slug
    workflow_id = _make_workflow(auth_client, slug, "garbage token wf")
    session_id, _token = _create_and_authorize(auth_client, slug, workflow_id)
    ext = _fresh_client()

    missing = ext.post(f"/api/{slug}/recording-sessions/{session_id}/extension-connect", json={"extension_token": "not-a-real-token"})
    assert missing.status_code == 401

    no_creds_step = ext.post(f"/api/{slug}/recording-sessions/{session_id}/steps", json={"step_type": "SCREENSHOT"})
    assert no_creds_step.status_code == 401

    # Cleanup -- this session never got past REQUESTED.
    auth_client.post(f"/api/{slug}/recording-sessions/{session_id}/discard")


def test_extension_idempotent_step_replay(auth_client, project_slug):
    slug = project_slug
    workflow_id = _make_workflow(auth_client, slug, "idempotent ext wf")
    session_id, token = _create_and_authorize(auth_client, slug, workflow_id)
    ext = _fresh_client()
    ext.post(f"/api/{slug}/recording-sessions/{session_id}/extension-connect", json={"extension_token": token})

    first = ext.post(
        f"/api/{slug}/recording-sessions/{session_id}/steps",
        json={"step_type": "CLICK", "locator_strategy": "TEXT", "locator_value": "Submit", "extension_token": token, "idempotency_key": "ext-dup-1"},
    )
    replay = ext.post(
        f"/api/{slug}/recording-sessions/{session_id}/steps",
        json={"step_type": "CLICK", "locator_strategy": "TEXT", "locator_value": "Submit", "extension_token": token, "idempotency_key": "ext-dup-1"},
    )
    assert first.json()["id"] == replay.json()["id"]
    detail = auth_client.get(f"/api/{slug}/recording-sessions/{session_id}").json()
    assert len(detail["recorded_steps"]) == 1


def test_extension_authorization_expiry_marks_session_lost(auth_client, project_slug):
    slug = project_slug
    workflow_id = _make_workflow(auth_client, slug, "expiry ext wf")
    session_id, token = _create_and_authorize(auth_client, slug, workflow_id)
    ext = _fresh_client()
    ext.post(f"/api/{slug}/recording-sessions/{session_id}/extension-connect", json={"extension_token": token})

    from app import models as models_module
    from app.database import get_project_engine, open_project_session

    db = open_project_session(slug)
    try:
        auth_row = db.query(models_module.RecordingSessionAuthorization).filter(models_module.RecordingSessionAuthorization.recording_session_id == session_id).first()
        auth_row.expires_at = datetime.utcnow() - timedelta(seconds=1)
        db.commit()
    finally:
        db.close()

    detail = auth_client.get(f"/api/{slug}/recording-sessions/{session_id}").json()
    assert detail["status"] == "RUNNER_LOST"


def test_extension_cannot_undo_or_stop_a_stopped_session_twice(auth_client, project_slug):
    slug = project_slug
    workflow_id = _make_workflow(auth_client, slug, "double stop wf")
    session_id, token = _create_and_authorize(auth_client, slug, workflow_id)
    ext = _fresh_client()
    ext.post(f"/api/{slug}/recording-sessions/{session_id}/extension-connect", json={"extension_token": token})
    ext.post(f"/api/{slug}/recording-sessions/{session_id}/steps", json={"step_type": "SCREENSHOT", "extension_token": token})
    stop1 = ext.post(f"/api/{slug}/recording-sessions/{session_id}/stop", params={"extension_token": token})
    assert stop1.status_code == 200

    # The token was revoked by stop1 -- a second stop attempt (with the
    # now-revoked token) must be rejected, not silently accepted.
    stop2 = ext.post(f"/api/{slug}/recording-sessions/{session_id}/stop", params={"extension_token": token})
    assert stop2.status_code == 401
