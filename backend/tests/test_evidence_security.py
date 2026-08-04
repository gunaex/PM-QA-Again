"""Phase 7 requirement 4 — evidence upload/download abuse cases."""

from app.database import get_project_db
from app.storage import get_evidence_storage
from app.evidence_utils import MAX_EVIDENCE_SIZE_BYTES

from .conftest import _make_png


def test_oversized_file_is_rejected(auth_client, project_slug, result_ref):
    cycle_id, result_id = result_ref
    slug = project_slug
    oversized = b"\x89PNG\r\n\x1a\n" + b"\x00" * (MAX_EVIDENCE_SIZE_BYTES + 1)
    r = auth_client.post(
        f"/api/{slug}/cycles/{cycle_id}/results/{result_id}/evidence",
        files={"file": ("big.png", oversized, "image/png")},
    )
    assert r.status_code == 400
    assert "MB limit" in r.json()["detail"]


def test_malicious_filename_never_reaches_the_storage_key_or_disk(auth_client, project_slug, result_ref):
    """A path-traversal filename must not escape the evidence directory —
    the stored object_key is always {uuid}.{ext}, never derived from the
    client-supplied name (ADR-0002 requirement 5), and the filename kept
    as metadata is sanitized to a safe character set."""
    cycle_id, result_id = result_ref
    slug = project_slug
    evil_name = "../../../../etc/passwd.png"
    r = auth_client.post(
        f"/api/{slug}/cycles/{cycle_id}/results/{result_id}/evidence",
        files={"file": (evil_name, _make_png(b"\x91"), "image/png")},
    )
    assert r.status_code == 200
    item = r.json()

    # Sanitized metadata filename — no path separators, no "..".
    assert "/" not in item["original_filename"]
    assert ".." not in item["original_filename"]

    # The actual on-disk object key is never derived from the filename.
    db = next(get_project_db(slug))
    try:
        from app import models

        object_key = db.query(models.EvidenceItem.object_key).filter(models.EvidenceItem.id == item["id"]).scalar()
    finally:
        db.close()
    assert ".." not in object_key
    assert object_key.startswith(f"evidence/{slug}/{result_id}/")


def test_evidence_from_one_project_is_not_reachable_through_another_projects_slug(auth_client, project_slug, result_ref):
    cycle_id, result_id = result_ref
    slug_a = project_slug
    evidence = auth_client.post(
        f"/api/{slug_a}/cycles/{cycle_id}/results/{result_id}/evidence",
        files={"file": ("secret.png", _make_png(b"\xa2"), "image/png")},
    ).json()

    slug_b = auth_client.post("/api/projects", json={"name": "Evidence Isolation B"}).json()["slug"]
    # Project B has no such cycle/result at all — any attempt to reach
    # project A's evidence via project B's URL space must 404, never
    # accidentally resolve project A's row (each project is a distinct
    # SQLite file, so this also proves get_project_db's isolation holds
    # for evidence specifically, not just suites).
    r = auth_client.get(f"/api/{slug_b}/cycles/{cycle_id}/results/{result_id}/evidence/{evidence['id']}")
    assert r.status_code == 404


def test_download_always_requests_a_short_presigned_expiry(auth_client, project_slug, result_ref, monkeypatch):
    """Requirement 7 (Phase 7's own item, restated from ADR-0002
    requirement 3) — presigned URLs must be short-lived. Verifies the
    download route's actual call, not just that the storage class
    supports an expiry parameter."""
    cycle_id, result_id = result_ref
    slug = project_slug
    evidence = auth_client.post(
        f"/api/{slug}/cycles/{cycle_id}/results/{result_id}/evidence",
        files={"file": ("expiry-check.png", _make_png(b"\xb3"), "image/png")},
    ).json()

    from app.storage.filesystem import FilesystemEvidenceStorage

    captured = {}
    original = FilesystemEvidenceStorage.presigned_get_url

    def spy(self, key, expires_in=300, response_filename=None, response_content_type=None):
        captured["expires_in"] = expires_in
        return original(self, key, expires_in, response_filename, response_content_type)

    monkeypatch.setattr(FilesystemEvidenceStorage, "presigned_get_url", spy)
    auth_client.get(f"/api/{slug}/cycles/{cycle_id}/results/{result_id}/evidence/{evidence['id']}/original")
    assert captured["expires_in"] <= 300, "presigned evidence URLs must be short-lived"


def test_viewer_can_download_evidence_but_not_upload_or_archive(auth_client, project_slug, result_ref):
    cycle_id, result_id = result_ref
    slug = project_slug
    evidence = auth_client.post(
        f"/api/{slug}/cycles/{cycle_id}/results/{result_id}/evidence",
        files={"file": ("viewer-check.png", _make_png(b"\xc4"), "image/png")},
    ).json()

    from fastapi.testclient import TestClient
    from app.main import app

    created = auth_client.post(
        "/api/auth/users", json={"email": "viewer2@example.com", "password": "ViewerPass123!", "role": "VIEWER"}
    )
    # ADR-0003: grant explicit project-membership so this test keeps
    # asserting the role boundary (read vs write) rather than the access
    # boundary.
    project_id = auth_client.get(f"/api/projects/{slug}").json()["id"]
    auth_client.post(f"/api/auth/users/{created.json()['id']}/projects", json={"project_id": project_id})
    viewer = TestClient(app)
    viewer.headers.update({"Origin": "http://localhost:5173"})
    viewer.post("/api/auth/login", json={"email": "viewer2@example.com", "password": "ViewerPass123!"})
    viewer.post("/api/auth/change-password", json={"current_password": "ViewerPass123!", "new_password": "ViewerPass456!"})

    read = viewer.get(f"/api/{slug}/cycles/{cycle_id}/results/{result_id}/evidence/{evidence['id']}/original")
    assert read.status_code == 200

    upload = viewer.post(
        f"/api/{slug}/cycles/{cycle_id}/results/{result_id}/evidence",
        files={"file": ("nope.png", _make_png(b"\xd5"), "image/png")},
    )
    assert upload.status_code == 403

    archive = viewer.put(f"/api/{slug}/cycles/{cycle_id}/results/{result_id}/evidence/{evidence['id']}/archive")
    assert archive.status_code == 403
