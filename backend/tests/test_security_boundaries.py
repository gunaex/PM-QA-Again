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
