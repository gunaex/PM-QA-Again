"""HYB-5 security/authorization gate: adversarial tests against the real
running app (TestClient), backing docs/HYBRID_RUNNER_THREAT_MODEL.md's
claims with executable proof rather than narrative alone. Every test
here drives the actual FastAPI routes exactly as a real attacker/
misbehaving client would -- no mocked auth, no bypassed dependencies."""
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
    return r.json()["token"], r.json()["id"]


def _make_published_workflow(auth_client, slug, name="sec wf", n_steps=1, with_checkpoint=False):
    wf = auth_client.post(f"/api/{slug}/workflows", json={"name": name}).json()
    rev = auth_client.post(f"/api/{slug}/workflows/{wf['id']}/revisions", json={"revision_label": "v1"}).json()
    step_ids = []
    for i in range(n_steps):
        s = auth_client.post(
            f"/api/{slug}/workflows/{wf['id']}/revisions/{rev['id']}/steps",
            json={"step_type": "SCREENSHOT", "description": f"step {i}"},
        ).json()
        step_ids.append(s["id"])
    cp_id = None
    if with_checkpoint:
        cp = auth_client.post(
            f"/api/{slug}/workflows/{wf['id']}/revisions/{rev['id']}/steps",
            json={"step_type": "MANUAL_CHECKPOINT", "description": "cp", "checkpoint_instructions": "check"},
        ).json()
        cp_id = cp["id"]
    auth_client.post(f"/api/{slug}/workflows/{wf['id']}/revisions/{rev['id']}/publish")
    return wf["id"], rev["id"], step_ids, cp_id


# ---------- Runner credential lifecycle ----------


def test_runner_registration_requires_admin(auth_client, project_slug):
    """Runner-token minting (POST /api/runner-tokens) is ADMIN-only --
    require_admin rejects anyone without a valid human session outright
    (401), and a runner cannot use its own execution credential to
    self-issue further runner tokens (also 401, since RunnerToken auth
    isn't a User session at all). Generic TESTER/VIEWER-vs-ADMIN role
    boundaries are already covered by test_security_boundaries.py; this
    test avoids adding another /api/auth/login call, which would tip the
    session-wide 5/minute login rate limit (shared across the whole test
    session by remote address) into failing unrelated tests."""
    anon = _fresh_client()
    anon_denied = anon.post("/api/runner-tokens", json={"label": "anon-attempt"})
    assert anon_denied.status_code == 401

    token, _ = _issue_runner_token(auth_client, "self-issue-attempt-runner")
    runner = _fresh_client()
    runner.headers.update({"X-Runner-Token": token})
    runner_denied = runner.post("/api/runner-tokens", json={"label": "runner-self-issued"})
    assert runner_denied.status_code == 401


def test_revoked_runner_token_is_rejected_everywhere(auth_client, project_slug):
    slug = project_slug
    token, token_id = _issue_runner_token(auth_client, "revoke-target")
    _, revision_id, _, _ = _make_published_workflow(auth_client, slug, name="revoke wf")
    auth_client.post(f"/api/{slug}/workflow-runs", json={"workflow_revision_id": revision_id})

    runner = _fresh_client()
    runner.headers.update({"X-Runner-Token": token})
    ok = runner.post(f"/api/{slug}/workflow-runs/claim")
    assert ok.status_code == 200 and ok.json()["claimed"] is True

    revoke = auth_client.put(f"/api/runner-tokens/{token_id}/revoke")
    assert revoke.status_code == 200
    assert revoke.json()["status"] == "REVOKED"

    rejected = runner.post(f"/api/{slug}/workflow-runs/claim")
    assert rejected.status_code == 401

    # Every other runner-authenticated surface must reject it too, not
    # just /claim.
    rejected_hb = runner.post(f"/api/{slug}/workflow-runs/1/heartbeat", json={"lease_token": "whatever"})
    assert rejected_hb.status_code == 401


def test_missing_runner_token_header_is_rejected(project_slug):
    slug = project_slug
    anon = _fresh_client()
    r = anon.post(f"/api/{slug}/workflow-runs/claim")
    assert r.status_code == 401


def test_garbage_runner_token_is_rejected(project_slug):
    slug = project_slug
    runner = _fresh_client()
    runner.headers.update({"X-Runner-Token": "not-a-real-token-at-all"})
    r = runner.post(f"/api/{slug}/workflow-runs/claim")
    assert r.status_code == 401


# ---------- Cross-project runner access (documented trust boundary) ----------


def test_runner_token_is_a_global_credential_not_project_scoped(auth_client):
    """Documented existing trust boundary (see
    docs/HYBRID_RUNNER_THREAT_MODEL.md "Cross-project runner access"):
    RunnerToken lives in the master DB with no project_id, exactly like
    every human ADMIN/TESTER user in this app -- there is no per-project
    membership model for ANY actor today, human or runner. A token
    issued while working on project A can claim jobs in project B. This
    test exists so that fact is executable, verified documentation, not
    an assumption -- and so a future change that silently narrows or
    removes this property is a deliberate decision, not an accident."""
    slug_a = auth_client.post("/api/projects", json={"name": "Cross Proj A"}).json()["slug"]
    slug_b = auth_client.post("/api/projects", json={"name": "Cross Proj B"}).json()["slug"]

    _, rev_b, _, _ = _make_published_workflow(auth_client, slug_b, name="cross wf b")
    auth_client.post(f"/api/{slug_b}/workflow-runs", json={"workflow_revision_id": rev_b})

    token, _ = _issue_runner_token(auth_client, "cross-project-runner")
    runner = _fresh_client()
    runner.headers.update({"X-Runner-Token": token})

    # Claiming against project A (nothing queued there) correctly finds
    # nothing -- but the credential itself is honored identically.
    claim_a = runner.post(f"/api/{slug_a}/workflow-runs/claim")
    assert claim_a.status_code == 200
    assert claim_a.json()["claimed"] is False

    claim_b = runner.post(f"/api/{slug_b}/workflow-runs/claim")
    assert claim_b.status_code == 200
    assert claim_b.json()["claimed"] is True


# ---------- Lease/actor boundary ----------


def test_invalid_lease_ownership_is_rejected(auth_client, project_slug):
    slug = project_slug
    _, revision_id, step_ids, _ = _make_published_workflow(auth_client, slug, name="lease wf")
    auth_client.post(f"/api/{slug}/workflow-runs", json={"workflow_revision_id": revision_id})

    token_a, _ = _issue_runner_token(auth_client, "lease-runner-a")
    runner_a = _fresh_client()
    runner_a.headers.update({"X-Runner-Token": token_a})
    claim = runner_a.post(f"/api/{slug}/workflow-runs/claim").json()
    run_id = claim["run"]["id"]

    # A second, distinct runner (different token) never held this lease.
    token_b, _ = _issue_runner_token(auth_client, "lease-runner-b")
    runner_b = _fresh_client()
    runner_b.headers.update({"X-Runner-Token": token_b})
    forged = runner_b.post(f"/api/{slug}/workflow-runs/{run_id}/heartbeat", json={"lease_token": claim["lease_token"]})
    assert forged.status_code == 409

    wrong_token_value = runner_a.post(f"/api/{slug}/workflow-runs/{run_id}/heartbeat", json={"lease_token": "forged-value"})
    assert wrong_token_value.status_code == 409


def test_replayed_event_with_same_idempotency_key_does_not_duplicate(auth_client, project_slug):
    slug = project_slug
    _, revision_id, step_ids, _ = _make_published_workflow(auth_client, slug, name="replay wf")
    auth_client.post(f"/api/{slug}/workflow-runs", json={"workflow_revision_id": revision_id})
    token, _ = _issue_runner_token(auth_client, "replay-runner")
    runner = _fresh_client()
    runner.headers.update({"X-Runner-Token": token})
    claim = runner.post(f"/api/{slug}/workflow-runs/claim").json()
    run_id = claim["run"]["id"]
    lease_token = claim["lease_token"]

    first = runner.post(
        f"/api/{slug}/workflow-runs/{run_id}/events",
        json={"event_type": "HEARTBEAT", "idempotency_key": "replay-key", "lease_token": lease_token},
    )
    replay = runner.post(
        f"/api/{slug}/workflow-runs/{run_id}/events",
        json={"event_type": "HEARTBEAT", "idempotency_key": "replay-key", "lease_token": lease_token},
    )
    assert first.json()["id"] == replay.json()["id"]

    events = auth_client.get(f"/api/{slug}/workflow-runs/{run_id}").json()["events"]
    assert sum(1 for e in events if e.get("idempotency_key") == "replay-key") == 1


def test_duplicate_claim_by_second_runner_is_rejected(auth_client, project_slug):
    slug = project_slug
    _, revision_id, step_ids, _ = _make_published_workflow(auth_client, slug, name="dup claim wf")
    auth_client.post(f"/api/{slug}/workflow-runs", json={"workflow_revision_id": revision_id})
    token_a, _ = _issue_runner_token(auth_client, "dup-claim-a")
    token_b, _ = _issue_runner_token(auth_client, "dup-claim-b")
    runner_a = _fresh_client()
    runner_a.headers.update({"X-Runner-Token": token_a})
    runner_b = _fresh_client()
    runner_b.headers.update({"X-Runner-Token": token_b})

    first = runner_a.post(f"/api/{slug}/workflow-runs/claim")
    assert first.json()["claimed"] is True
    second = runner_b.post(f"/api/{slug}/workflow-runs/claim")
    assert second.json()["claimed"] is False  # queue was already empty -- no duplicate execution


# ---------- Invalid state transitions ----------


def test_checkpoint_resume_without_waiting_state_is_rejected(auth_client, project_slug):
    slug = project_slug
    _, revision_id, step_ids, cp_id = _make_published_workflow(auth_client, slug, name="bad resume wf", with_checkpoint=True)
    auth_client.post(f"/api/{slug}/workflow-runs", json={"workflow_revision_id": revision_id})
    token, _ = _issue_runner_token(auth_client, "bad-resume-runner")
    runner = _fresh_client()
    runner.headers.update({"X-Runner-Token": token})
    claim = runner.post(f"/api/{slug}/workflow-runs/claim").json()
    run_id = claim["run"]["id"]
    lease_token = claim["lease_token"]

    # Never entered WAITING_FOR_HUMAN -- a resume attempt must be rejected,
    # not silently treated as a no-op success.
    resume = runner.post(f"/api/{slug}/workflow-runs/{run_id}/checkpoint-resume", json={"workflow_step_id": cp_id, "lease_token": lease_token})
    assert resume.status_code == 409


def test_checkpoint_decision_on_non_waiting_run_is_rejected(auth_client, project_slug):
    slug = project_slug
    _, revision_id, step_ids, cp_id = _make_published_workflow(auth_client, slug, name="no wait wf", with_checkpoint=True)
    queued = auth_client.post(f"/api/{slug}/workflow-runs", json={"workflow_revision_id": revision_id}).json()
    # Run is QUEUED, never claimed, never WAITING_FOR_HUMAN.
    decide = auth_client.post(
        f"/api/{slug}/workflow-runs/{queued['id']}/checkpoint-decision",
        json={"workflow_step_id": cp_id, "status": "PASS", "actual_result_md": "ok"},
    )
    assert decide.status_code == 409
    # Cancel so this leftover QUEUED run doesn't get claimed by a later,
    # unrelated test in this shared session-scoped project (claim() picks
    # the oldest QUEUED run FIFO across the whole project).
    auth_client.post(f"/api/{slug}/workflow-runs/{queued['id']}/cancel")


# ---------- Actor-type boundary: human vs runner ----------


def test_runner_cannot_submit_a_human_checkpoint_decision(auth_client, project_slug):
    """/checkpoint-decision requires a real user session (require_tester)
    -- a runner presenting only its X-Runner-Token (no cookies) must be
    rejected outright, never accepted as if it were a human decision."""
    slug = project_slug
    _, revision_id, step_ids, cp_id = _make_published_workflow(auth_client, slug, name="actor wf", with_checkpoint=True)
    queued = auth_client.post(f"/api/{slug}/workflow-runs", json={"workflow_revision_id": revision_id}).json()
    token, _ = _issue_runner_token(auth_client, "actor-boundary-runner")
    runner = _fresh_client()
    runner.headers.update({"X-Runner-Token": token})

    # 401 fires on the auth dependency before the route body ever runs
    # (require_tester needs a real cookie/JWT session), regardless of
    # which run id is named -- the run's actual status is irrelevant here.
    forged_human_decision = runner.post(
        f"/api/{slug}/workflow-runs/{queued['id']}/checkpoint-decision",
        json={"workflow_step_id": cp_id, "status": "PASS", "actual_result_md": "forged"},
    )
    assert forged_human_decision.status_code == 401
    # Cancel so this leftover QUEUED run doesn't get claimed by a later,
    # unrelated test in this shared session-scoped project.
    auth_client.post(f"/api/{slug}/workflow-runs/{queued['id']}/cancel")


def test_human_session_cannot_submit_runner_events(auth_client, project_slug):
    """/events requires get_current_runner (X-Runner-Token) -- a logged-in
    human user's cookie session must not be accepted as a runner event
    source, even though they're a legitimate authenticated user for
    every human-facing endpoint."""
    slug = project_slug
    _, revision_id, step_ids, _ = _make_published_workflow(auth_client, slug, name="human as runner wf")
    queued = auth_client.post(f"/api/{slug}/workflow-runs", json={"workflow_revision_id": revision_id}).json()
    forged_event = auth_client.post(
        f"/api/{slug}/workflow-runs/{queued['id']}/events",
        json={"event_type": "STEP_COMPLETED", "lease_token": "irrelevant"},
    )
    assert forged_event.status_code == 401
    auth_client.post(f"/api/{slug}/workflow-runs/{queued['id']}/cancel")


def test_decided_by_identity_is_server_derived_never_client_supplied(auth_client, project_slug):
    """A client cannot forge decided_by_email/decided_by_user_id via the
    request body -- the server always uses the authenticated session's
    own identity, matching the app's established server-derived-actor
    discipline used everywhere else (executed_by, published_by, etc)."""
    slug = project_slug
    _, revision_id, step_ids, cp_id = _make_published_workflow(auth_client, slug, name="identity wf", with_checkpoint=True)
    auth_client.post(f"/api/{slug}/workflow-runs", json={"workflow_revision_id": revision_id})
    token, _ = _issue_runner_token(auth_client, "identity-runner")
    runner = _fresh_client()
    runner.headers.update({"X-Runner-Token": token})
    claim = runner.post(f"/api/{slug}/workflow-runs/claim").json()
    run_id = claim["run"]["id"]
    lease_token = claim["lease_token"]
    runner.post(f"/api/{slug}/workflow-runs/{run_id}/step-runs", json={"workflow_step_id": cp_id, "lease_token": lease_token})
    runner.post(
        f"/api/{slug}/workflow-runs/{run_id}/events",
        json={"event_type": "CHECKPOINT_WAITING", "actor_type": "RUNNER", "lease_token": lease_token, "payload_json": f'{{"step_id":{cp_id}}}'},
    )

    decide = auth_client.post(
        f"/api/{slug}/workflow-runs/{run_id}/checkpoint-decision",
        json={
            "workflow_step_id": cp_id,
            "status": "PASS",
            "actual_result_md": "ok",
            # An attacker-controlled body attempting identity spoofing --
            # these fields don't even exist on the accepted schema, but
            # confirm the response reflects the real session regardless.
            "decided_by_email": "attacker@evil.example",
            "decided_by_user_id": 99999,
        },
    )
    assert decide.status_code == 200, decide.text
    assert decide.json()["decided_by_email"] == "admin@example.com"
    assert decide.json()["decided_by_email"] != "attacker@evil.example"


def test_human_fail_cannot_be_overridden_by_later_automation_or_racing_decision(auth_client, project_slug):
    slug = project_slug
    _, revision_id, step_ids, cp_id = _make_published_workflow(auth_client, slug, name="fail terminal wf", with_checkpoint=True)
    auth_client.post(f"/api/{slug}/workflow-runs", json={"workflow_revision_id": revision_id})
    token, _ = _issue_runner_token(auth_client, "fail-terminal-runner")
    runner = _fresh_client()
    runner.headers.update({"X-Runner-Token": token})
    claim = runner.post(f"/api/{slug}/workflow-runs/claim").json()
    run_id = claim["run"]["id"]
    lease_token = claim["lease_token"]
    runner.post(f"/api/{slug}/workflow-runs/{run_id}/step-runs", json={"workflow_step_id": cp_id, "lease_token": lease_token})
    runner.post(
        f"/api/{slug}/workflow-runs/{run_id}/events",
        json={"event_type": "CHECKPOINT_WAITING", "actor_type": "RUNNER", "lease_token": lease_token, "payload_json": f'{{"step_id":{cp_id}}}'},
    )
    fail = auth_client.post(
        f"/api/{slug}/workflow-runs/{run_id}/checkpoint-decision",
        json={"workflow_step_id": cp_id, "status": "FAIL", "actual_result_md": "broken"},
    )
    assert fail.status_code == 200

    # A racing second HUMAN decision cannot override it.
    racing = auth_client.post(
        f"/api/{slug}/workflow-runs/{run_id}/checkpoint-decision",
        json={"workflow_step_id": cp_id, "status": "PASS", "actual_result_md": "actually fine"},
    )
    assert racing.status_code == 409

    # The runner (automation) cannot resume/complete-as-PASSED past a FAIL either.
    resume = runner.post(f"/api/{slug}/workflow-runs/{run_id}/checkpoint-resume", json={"workflow_step_id": cp_id, "lease_token": lease_token})
    assert resume.status_code == 409

    run_after = auth_client.get(f"/api/{slug}/workflow-runs/{run_id}").json()
    assert run_after["status"] == "FAILED"


# ---------- Sensitive variable handling ----------


def test_sensitive_step_rejects_a_raw_secret_value(auth_client, project_slug):
    """A sensitive step's input_value must be a ${VAR} placeholder --
    never a literal secret. The real secret is only ever resolved inside
    the runner's own local environment (see runner/.env), so it never
    enters this app's DB/logs/events/exports in the first place."""
    slug = project_slug
    wf = auth_client.post(f"/api/{slug}/workflows", json={"name": "secret wf"}).json()
    rev = auth_client.post(f"/api/{slug}/workflows/{wf['id']}/revisions", json={"revision_label": "v1"}).json()
    rejected = auth_client.post(
        f"/api/{slug}/workflows/{wf['id']}/revisions/{rev['id']}/steps",
        json={"step_type": "FILL", "description": "password field", "is_sensitive": True, "input_value": "hunter2literalpassword"},
    )
    assert rejected.status_code == 400
    accepted = auth_client.post(
        f"/api/{slug}/workflows/{wf['id']}/revisions/{rev['id']}/steps",
        json={
            "step_type": "FILL",
            "description": "password field",
            "is_sensitive": True,
            "input_value": "${SECRET_LOGIN_PASSWORD}",
            "locator_strategy": "LABEL",
            "locator_value": "Password",
        },
    )
    assert accepted.status_code == 200, accepted.text


# ---------- Export filename/path safety ----------


def test_zip_export_sanitizes_malicious_checkpoint_code_in_filename(auth_client, project_slug):
    """A checkpoint_code containing path-traversal characters must never
    produce a ZIP entry that escapes the evidence/ prefix -- report_zip's
    _safe_slug strips everything but [A-Za-z0-9_-]."""
    import io
    import zipfile

    slug = project_slug
    suite = auth_client.post(f"/api/{slug}/suites", json={"name": "Malicious Suite"}).json()
    revision = auth_client.post(f"/api/{slug}/suites/{suite['id']}/revisions", json={"revision_label": "rv1"}).json()
    auth_client.post(
        f"/api/{slug}/revisions/{revision['id']}/cases",
        json={"checkpoint_code": "../../etc/passwd", "title": "c", "action_md": "a", "expected_result_md": "e"},
    )
    auth_client.post(f"/api/{slug}/suites/{suite['id']}/revisions/{revision['id']}/publish")
    cycle = auth_client.post(
        f"/api/{slug}/cycles",
        json={"suite_id": suite["id"], "script_revision_id": revision["id"], "name": "malicious cycle", "environment": "test"},
    ).json()
    result_id = auth_client.get(f"/api/{slug}/cycles/{cycle['id']}/results").json()[0]["id"]
    auth_client.put(f"/api/{slug}/cycles/{cycle['id']}/results/{result_id}", json={"status": "PASS", "actual_result_md": "ok"})
    auth_client.post(
        f"/api/{slug}/cycles/{cycle['id']}/results/{result_id}/evidence",
        files={"file": ("shot.png", PNG_BYTES, "image/png")},
    )

    r = auth_client.get(f"/api/{slug}/cycles/{cycle['id']}/export/zip")
    assert r.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    for name in zf.namelist():
        assert ".." not in name
        assert not name.startswith("/")
        if name.startswith("evidence/"):
            assert name == "evidence/" + name.split("/", 1)[1]  # still confined under evidence/


# ---------- CORS/CSRF boundary already covered for Track A; confirm it
# ---------- also protects the hybrid workflow-run write endpoints. ----------


def test_hybrid_endpoint_cookie_write_without_origin_is_rejected(auth_client, project_slug):
    slug = project_slug
    _, revision_id, step_ids, _ = _make_published_workflow(auth_client, slug, name="csrf wf")
    no_origin_client = TestClient(app)
    no_origin_client.cookies.update(auth_client.cookies)
    r = no_origin_client.post(f"/api/{slug}/workflow-runs", json={"workflow_revision_id": revision_id})
    assert r.status_code == 403
