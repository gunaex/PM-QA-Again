import logging
import os
import time
from urllib.parse import urlsplit

from dotenv import load_dotenv

# Must run before any of this app's modules are imported — auth.py reads
# JWT_SECRET_KEY at import time, so loading .env any later would be too late.
load_dotenv()

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from slowapi.errors import RateLimitExceeded  # noqa: E402

from .database import MasterBase, master_engine, MasterSessionLocal, ensure_columns, MASTER_COLUMN_PATCHES  # noqa: E402
from .routers import (  # noqa: E402
    auth,
    projects,
    suites,
    revisions,
    cases,
    cycles,
    cycle_results,
    evidence,
    defects,
    signoffs,
    dashboard,
    reports,
    exports,
    runner_tokens,
    hybrid,
    workflows,
    workflow_runs,
    recording_sessions,
    hybrid_reports,
    quick_test,
)
from .seed import seed_bootstrap_admin  # noqa: E402
from .rate_limit import limiter  # noqa: E402

MasterBase.metadata.create_all(bind=master_engine)
ensure_columns(master_engine, MASTER_COLUMN_PATCHES)

with MasterSessionLocal() as _db:
    seed_bootstrap_admin(_db)

app = FastAPI(title="QA-Again API")

app.state.limiter = limiter

# Own handler + level, independent of uvicorn's root logging config, so
# these lines are visible during local development without extra setup.
perf_logger = logging.getLogger("perf")
perf_logger.setLevel(logging.INFO)
if not perf_logger.handlers:
    _perf_handler = logging.StreamHandler()
    _perf_handler.setFormatter(logging.Formatter("[perf] %(message)s"))
    perf_logger.addHandler(_perf_handler)
    perf_logger.propagate = False


@app.middleware("http")
async def request_timing_log(request: Request, call_next):
    """Development-only visibility into slow endpoints. Logs method, path,
    status, and duration -- never query strings, headers, cookies, or
    bodies, so no secrets/tokens/evidence content ever reach the log."""
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000
    response.headers["Server-Timing"] = f'app;dur={duration_ms:.1f}'
    response.headers["X-Response-Time-Ms"] = f"{duration_ms:.1f}"
    perf_logger.info("%s %s -> %s in %.1fms", request.method, request.url.path, response.status_code, duration_ms)
    return response


@app.exception_handler(RateLimitExceeded)
def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(status_code=429, content={"detail": "Too many requests — please slow down."})


# Comma-separated list of allowed CORS origins. Defaults to the local Vite
# dev server so `uvicorn` run locally behaves exactly as before; set
# ALLOWED_ORIGINS in production to the deployed Cloudflare Pages origin(s).
# allow_credentials=True + an explicit origin list (never "*") is required
# for the auth cookies to actually be sent cross-origin.
_allowed_origins = [
    o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "http://localhost:5173").split(",") if o.strip()
]
_allow_local_dev_origins = os.environ.get("ALLOW_LOCAL_DEV_ORIGINS", "false").lower() in ("1", "true", "yes")
_local_dev_origin_regex = r"http://(?:localhost|127\.0\.0\.1):\d+" if _allow_local_dev_origins else None

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_origin_regex=_local_dev_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _origin_is_allowed(origin_or_referer: str) -> bool:
    # Referer (fallback when Origin is absent) includes a path — reduce
    # both sides to scheme+host before comparing.
    parsed = urlsplit(origin_or_referer)
    candidate = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
    if (
        _allow_local_dev_origins
        and parsed.scheme == "http"
        and parsed.hostname in ("localhost", "127.0.0.1")
        and parsed.port is not None
    ):
        return True
    return any(candidate == o.rstrip("/") for o in _allowed_origins)


@app.middleware("http")
async def csrf_origin_check(request: Request, call_next):
    """Cookie-based sessions are SameSite=None in production (required —
    frontend and backend are different origins), which means the cookie
    IS sent on cross-site requests. CORS's allow_origins stops a
    malicious page's JS from *reading* our responses, but does not by
    itself stop a CORS-"simple" cross-site request (e.g. a forged
    multipart/form-data POST, which needs no preflight) from being sent
    with the victim's cookie attached and executing server-side. JSON
    endpoints are already safe (a custom Content-Type forces a preflight
    that allow_origins blocks) — this closes the gap for the ones that
    aren't, e.g. evidence upload.

    Only applies to cookie-authenticated requests: a request bearing an
    `Authorization: Bearer` token instead isn't exposed the same way — a
    browser never auto-attaches a bearer token to a forged request the
    way it does a cookie.
    """
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        has_session_cookie = "access_token" in request.cookies
        has_bearer = request.headers.get("Authorization", "").startswith("Bearer ")
        if has_session_cookie and not has_bearer:
            origin = request.headers.get("origin") or request.headers.get("referer")
            if not origin or not _origin_is_allowed(origin):
                return JSONResponse(status_code=403, content={"detail": "Cross-origin request rejected"})
    return await call_next(request)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = "default-src 'self'"
    return response


app.include_router(auth.router)
app.include_router(projects.router)
app.include_router(suites.router)
app.include_router(revisions.router)
app.include_router(cases.router)
app.include_router(cycles.router)
app.include_router(cycle_results.router)
app.include_router(evidence.router)
app.include_router(defects.router)
app.include_router(signoffs.router)
app.include_router(dashboard.router)
app.include_router(reports.router)
app.include_router(exports.router)
app.include_router(runner_tokens.router)
app.include_router(hybrid.router)
app.include_router(workflows.router)
app.include_router(workflow_runs.router)
app.include_router(recording_sessions.router)
app.include_router(hybrid_reports.router)
app.include_router(quick_test.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
