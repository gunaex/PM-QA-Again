import os
import shutil

TEST_DATA_DIR = os.path.join(os.path.dirname(__file__), "_tmp_data")
if os.path.exists(TEST_DATA_DIR):
    shutil.rmtree(TEST_DATA_DIR)

# Must be set before `app.*` is imported anywhere — auth.py/database.py
# read these at import time.
os.environ["DATA_DIR"] = TEST_DATA_DIR
os.environ["JWT_SECRET_KEY"] = "test-secret-not-for-production"
os.environ["ADMIN_EMAIL"] = "admin@example.com"
os.environ["ADMIN_PASSWORD"] = "changeme123"
os.environ["ALLOW_LOCAL_DEV_ORIGINS"] = "true"
os.environ.setdefault("STORAGE_BACKEND", "filesystem")
os.environ.setdefault("EXECUTION_PROVIDER", "local")

import struct
import zlib

import pytest
from fastapi.testclient import TestClient

from app.main import app


def _make_png(seed: bytes = b"\x00") -> bytes:
    """A genuinely valid 2x2 PNG, content varying by `seed` so tests can
    produce distinct sha256 hashes on demand."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0))
    row = seed + b"\xff\x00\x00" * 2
    idat = chunk(b"IDAT", zlib.compress(row * 2))
    iend = chunk(b"IEND", b"")
    return sig + ihdr + idat + iend


PNG_BYTES = _make_png()


@pytest.fixture(scope="session")
def client():
    c = TestClient(app)
    # A real browser always sends Origin on state-changing requests — the
    # CSRF Origin check (main.py::csrf_origin_check) requires it for
    # cookie-authenticated writes. httpx's TestClient doesn't add this
    # automatically the way a browser does, so tests must set it
    # explicitly, matching ALLOWED_ORIGINS' local-dev default.
    c.headers.update({"Origin": "http://localhost:5173"})
    return c


@pytest.fixture(scope="session")
def auth_client(client):
    """Logs in once for the whole session — tests share this authenticated
    client, matching how the rest of this app's verification has always
    used one admin session per run."""
    r = client.post("/api/auth/login", json={"email": "admin@example.com", "password": "changeme123"})
    assert r.status_code == 200, r.text
    r = client.post(
        "/api/auth/change-password",
        json={"current_password": "changeme123", "new_password": "changeme456"},
    )
    assert r.status_code == 200, r.text
    return client


@pytest.fixture(scope="session")
def project_slug(auth_client):
    r = auth_client.post("/api/projects", json={"name": "Evidence Storage Tests"})
    assert r.status_code == 200, r.text
    return r.json()["slug"]


@pytest.fixture(scope="session")
def result_ref(auth_client, project_slug):
    """Creates suite -> published revision -> case -> cycle, returns
    (cycle_id, result_id) for evidence tests to attach to."""
    slug = project_slug
    suite = auth_client.post(f"/api/{slug}/suites", json={"name": "Suite", "suite_type": "REGRESSION"}).json()
    revision = auth_client.post(f"/api/{slug}/suites/{suite['id']}/revisions", json={"revision_label": "v1"}).json()
    auth_client.post(
        f"/api/{slug}/revisions/{revision['id']}/cases",
        json={
            "checkpoint_code": "REG-001",
            "title": "case",
            "action_md": "do it",
            "expected_result_md": "it works",
        },
    )
    auth_client.post(f"/api/{slug}/suites/{suite['id']}/revisions/{revision['id']}/publish")
    cycle = auth_client.post(
        f"/api/{slug}/cycles",
        json={"suite_id": suite["id"], "script_revision_id": revision["id"], "name": "cycle", "environment": "test"},
    ).json()
    results = auth_client.get(f"/api/{slug}/cycles/{cycle['id']}/results").json()
    return cycle["id"], results[0]["id"]
