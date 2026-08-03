"""Phase 7 requirement 3 — auth/authz/cookie/CORS/CSRF/rate-limit/role
verification against the real running app (TestClient), not just code
review."""

from fastapi.testclient import TestClient

from app.main import app


def _fresh_client():
    return TestClient(app)


# ---------- Role boundaries ----------


def test_viewer_can_read_but_not_write(auth_client, project_slug):
    """VIEWER is QA-Again's read-only role (ADR-0001 decision 2)."""
    created = auth_client.post(
        "/api/auth/users", json={"email": "viewer1@example.com", "password": "ViewerPass123!", "role": "VIEWER"}
    )
    assert created.status_code == 200, created.text
    # ADR-0003: a VIEWER also needs an explicit project-membership grant
    # to reach this project at all -- this test is about the role
    # boundary (read vs write), not the access boundary, so grant it here.
    project_id = auth_client.get(f"/api/projects/{project_slug}").json()["id"]
    auth_client.post(f"/api/auth/users/{created.json()['id']}/projects", json={"project_id": project_id})

    viewer = _fresh_client()
    viewer.headers.update({"Origin": "http://localhost:5173"})
    login = viewer.post("/api/auth/login", json={"email": "viewer1@example.com", "password": "ViewerPass123!"})
    assert login.status_code == 200
    # Bootstrap accounts created by an admin also start with
    # must_change_password — clear it so the rest of the boundary checks
    # aren't all masked by the same 403.
    viewer.post("/api/auth/change-password", json={"current_password": "ViewerPass123!", "new_password": "ViewerPass456!"})

    read = viewer.get(f"/api/{project_slug}/suites")
    assert read.status_code == 200, "VIEWER must be able to read"

    write = viewer.post(f"/api/{project_slug}/suites", json={"name": "should be rejected", "suite_type": "OTHER"})
    assert write.status_code == 403, "VIEWER must not be able to write"


def test_tester_cannot_admin_only_actions(auth_client, project_slug):
    created = auth_client.post(
        "/api/auth/users", json={"email": "tester1@example.com", "password": "TesterPass123!", "role": "TESTER"}
    )
    assert created.status_code == 200, created.text

    tester = _fresh_client()
    tester.headers.update({"Origin": "http://localhost:5173"})
    tester.post("/api/auth/login", json={"email": "tester1@example.com", "password": "TesterPass123!"})
    tester.post("/api/auth/change-password", json={"current_password": "TesterPass123!", "new_password": "TesterPass456!"})

    # Creating another user is ADMIN-only.
    r = tester.post("/api/auth/users", json={"email": "x@example.com", "password": "x", "role": "VIEWER"})
    assert r.status_code == 403


def test_unauthenticated_requests_are_rejected(project_slug):
    anon = _fresh_client()
    r = anon.get(f"/api/{project_slug}/suites")
    assert r.status_code == 401


def test_tampered_jwt_is_rejected(auth_client, project_slug):
    anon = _fresh_client()
    anon.cookies.set("access_token", "not-a-real-jwt.tampered.value")
    r = anon.get(f"/api/{project_slug}/suites")
    assert r.status_code == 401


# ---------- Cross-project isolation ----------


def test_project_data_is_isolated_by_slug(auth_client):
    """Each project is its own SQLite file — a suite created in project A
    must not be reachable (or even collide by numeric id) through
    project B's slug."""
    slug_a = auth_client.post("/api/projects", json={"name": "Isolation A"}).json()["slug"]
    slug_b = auth_client.post("/api/projects", json={"name": "Isolation B"}).json()["slug"]

    suite_a = auth_client.post(f"/api/{slug_a}/suites", json={"name": "only in A", "suite_type": "OTHER"}).json()

    # Same numeric id requested against project B's own suites collection
    # — must not leak project A's row (project B likely also has an id=1
    # of its own, or none yet; either way it must not be A's data).
    r = auth_client.get(f"/api/{slug_b}/suites/{suite_a['id']}")
    if r.status_code == 200:
        assert r.json()["name"] != "only in A", "a suite from another project's DB leaked across the slug boundary"
    else:
        assert r.status_code == 404


# ---------- Project membership (ADR-0003) ----------


def _create_role_user(auth_client, email, password, role):
    r = auth_client.post("/api/auth/users", json={"email": email, "password": password, "role": role})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _login_as(email, password, new_password):
    # /api/auth/login is rate-limited 5/minute (see test_login_is_rate_limited)
    # and its in-memory bucket is process-global/keyed by TestClient's shared
    # fake address -- this file logs in as a fresh user several times, which
    # would otherwise trip that shared bucket well before the real per-user
    # limit is the thing under test. Reset immediately before each real
    # login here, matching the reset already used by
    # test_login_is_rate_limited once it's done proving the limit exists.
    from app.rate_limit import limiter

    limiter.reset()
    c = _fresh_client()
    c.headers.update({"Origin": "http://localhost:5173"})
    login = c.post("/api/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    c.post("/api/auth/change-password", json={"current_password": password, "new_password": new_password})
    return c


def test_tester_with_no_membership_is_forbidden(auth_client, project_slug):
    _create_role_user(auth_client, "no-access-tester@example.com", "TesterPass123!", "TESTER")
    tester = _login_as("no-access-tester@example.com", "TesterPass123!", "TesterPass456!")

    r = tester.get(f"/api/{project_slug}/suites")
    assert r.status_code == 403, "a TESTER with no ProjectMembership row must be forbidden, not silently allowed"

    r_missing = tester.get("/api/genuinely-nonexistent-project-slug/suites")
    assert r_missing.status_code == 404, "a nonexistent project must 404 even before the membership check"


def test_tester_scoped_to_one_project_cannot_reach_another(auth_client):
    project_a = auth_client.post("/api/projects", json={"name": "Membership Scope A"}).json()
    project_b = auth_client.post("/api/projects", json={"name": "Membership Scope B"}).json()

    user_id = _create_role_user(auth_client, "scoped-tester@example.com", "TesterPass123!", "TESTER")
    grant = auth_client.post(f"/api/auth/users/{user_id}/projects", json={"project_id": project_a["id"]})
    assert grant.status_code == 200, grant.text

    tester = _login_as("scoped-tester@example.com", "TesterPass123!", "TesterPass456!")

    r_a = tester.get(f"/api/{project_a['slug']}/suites")
    assert r_a.status_code == 200, "TESTER must reach a project they're a member of"

    r_b = tester.get(f"/api/{project_b['slug']}/suites")
    assert r_b.status_code == 403, "TESTER must not reach a project they're not a member of"


def test_revoking_membership_blocks_further_access_without_relogin(auth_client):
    project = auth_client.post("/api/projects", json={"name": "Membership Revoke Test"}).json()
    user_id = _create_role_user(auth_client, "revoke-tester@example.com", "TesterPass123!", "TESTER")
    auth_client.post(f"/api/auth/users/{user_id}/projects", json={"project_id": project["id"]})

    tester = _login_as("revoke-tester@example.com", "TesterPass123!", "TesterPass456!")
    assert tester.get(f"/api/{project['slug']}/suites").status_code == 200

    revoke = auth_client.delete(f"/api/auth/users/{user_id}/projects/{project['id']}")
    assert revoke.status_code == 200

    # Same session/cookie, no re-login — access must already be gone.
    assert tester.get(f"/api/{project['slug']}/suites").status_code == 403


def test_admin_reaches_every_project_without_any_membership_row(auth_client):
    """ADMIN bypasses ProjectMembership entirely (ADR-0003) — the
    bootstrap admin account used by `auth_client` has zero membership
    rows for anything it creates, and must still reach it."""
    project = auth_client.post("/api/projects", json={"name": "Admin Bypass Test"}).json()
    r = auth_client.get(f"/api/{project['slug']}/suites")
    assert r.status_code == 200


def test_project_list_is_scoped_by_membership(auth_client):
    project_visible = auth_client.post("/api/projects", json={"name": "List Scope Visible"}).json()
    project_hidden = auth_client.post("/api/projects", json={"name": "List Scope Hidden"}).json()

    user_id = _create_role_user(auth_client, "list-scope-tester@example.com", "TesterPass123!", "TESTER")
    auth_client.post(f"/api/auth/users/{user_id}/projects", json={"project_id": project_visible["id"]})

    tester = _login_as("list-scope-tester@example.com", "TesterPass123!", "TesterPass456!")
    listed = tester.get("/api/projects").json()
    listed_slugs = {p["slug"] for p in listed}
    assert project_visible["slug"] in listed_slugs
    assert project_hidden["slug"] not in listed_slugs

    admin_listed = {p["slug"] for p in auth_client.get("/api/projects").json()}
    assert project_visible["slug"] in admin_listed
    assert project_hidden["slug"] in admin_listed


def test_tester_cannot_create_a_project(auth_client):
    """ADR-0003: project creation is ADMIN-only -- a TESTER's access to
    any project is always an explicit grant, never implicit from having
    created it."""
    user_id = _create_role_user(auth_client, "cannot-create-tester@example.com", "TesterPass123!", "TESTER")
    tester = _login_as("cannot-create-tester@example.com", "TesterPass123!", "TesterPass456!")
    r = tester.post("/api/projects", json={"name": "Should Be Rejected"})
    assert r.status_code == 403


def test_runner_fleet_status_is_readable_by_tester_not_just_admin(auth_client):
    """A TESTER queuing their own run needs to know whether a runner is
    even online -- unlike GET /api/runner-tokens (ADMIN-only, exposes
    labels/ids), this aggregate boolean is intentionally readable by
    any authenticated user, and must never leak per-runner details."""
    _create_role_user(auth_client, "fleet-status-tester@example.com", "TesterPass123!", "TESTER")
    tester = _login_as("fleet-status-tester@example.com", "TesterPass123!", "TesterPass456!")

    r = tester.get("/api/runner-tokens/status")
    assert r.status_code == 200, r.text
    assert set(r.json().keys()) == {"any_online"}
    assert isinstance(r.json()["any_online"], bool)

    anon = _fresh_client()
    assert anon.get("/api/runner-tokens/status").status_code == 401

    # Detailed list stays ADMIN-only regardless.
    assert tester.get("/api/runner-tokens").status_code == 403


# ---------- Rate limiting ----------


def test_login_is_rate_limited():
    """slowapi's 5/minute limit on /api/auth/login (routers/auth.py).

    The limiter's in-memory storage is process-global and keyed by
    remote address — every TestClient in this suite shares the same fake
    address, so deliberately exhausting the quota here would otherwise
    poison every other test file's real login calls for the rest of this
    pytest run (order-dependent flakiness, not a real app defect). Reset
    it immediately after this test proves the limit exists."""
    from app.rate_limit import limiter

    anon = _fresh_client()
    statuses = []
    for _ in range(7):
        r = anon.post("/api/auth/login", json={"email": "nobody@example.com", "password": "wrong"})
        statuses.append(r.status_code)
    assert 429 in statuses, f"expected a 429 within 7 rapid login attempts, got {statuses}"
    limiter.reset()


# ---------- CORS ----------


def test_cors_preflight_reflects_only_allowed_origin():
    anon = _fresh_client()
    r = anon.options(
        "/api/auth/login",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"

    r2 = anon.options(
        "/api/auth/login",
        headers={
            "Origin": "https://evil.example.com",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert r2.headers.get("access-control-allow-origin") != "https://evil.example.com"


def test_local_dev_fallback_port_is_allowed():
    anon = _fresh_client()
    r = anon.options(
        "/api/auth/login",
        headers={
            "Origin": "http://localhost:5174",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5174"

    loopback = anon.options(
        "/api/auth/login",
        headers={
            "Origin": "http://127.0.0.1:5174",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert loopback.headers.get("access-control-allow-origin") == "http://127.0.0.1:5174"


# ---------- CSRF (Origin check on cookie-authenticated writes) ----------



# NOTE: these tests reuse auth_client's already-established session
# cookie (copied onto a fresh client) rather than logging in again —
# the login endpoint is itself rate-limited (5/minute, see
# test_login_is_rate_limited below), and re-logging in from several
# tests in the same session risks tripping that shared bucket.


def test_cookie_authenticated_write_without_origin_is_rejected(auth_client, project_slug):
    no_origin_client = _fresh_client()  # no default Origin header
    no_origin_client.cookies.set("access_token", auth_client.cookies.get("access_token"))
    # Simulates a forged cross-site form POST riding the victim's cookie.
    r = no_origin_client.post(f"/api/{project_slug}/suites", json={"name": "csrf probe", "suite_type": "OTHER"})
    assert r.status_code == 403


def test_cookie_authenticated_write_with_wrong_origin_is_rejected(auth_client, project_slug):
    evil_client = _fresh_client()
    evil_client.headers.update({"Origin": "https://evil.example.com"})
    evil_client.cookies.set("access_token", auth_client.cookies.get("access_token"))
    r = evil_client.post(f"/api/{project_slug}/suites", json={"name": "csrf probe 2", "suite_type": "OTHER"})
    assert r.status_code == 403


def test_bearer_token_write_is_not_subject_to_origin_check(auth_client, project_slug):
    """A forged page can't make a browser attach an Authorization header
    the way it auto-attaches cookies — Bearer auth is out of CSRF's
    threat model, so it must not be blocked by the Origin check."""
    access_token = auth_client.cookies.get("access_token")
    assert access_token

    bearer_client = _fresh_client()  # no Origin header at all
    r = bearer_client.get(f"/api/{project_slug}/suites", headers={"Authorization": f"Bearer {access_token}"})
    assert r.status_code == 200, "Bearer-authenticated reads must work without an Origin header"
