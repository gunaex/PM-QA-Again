"""HYB-1 acceptance gate (docs/Autonomous hybird prompt.md's HYB-1
section) verified against the real running app (TestClient), not mocked."""
from fastapi.testclient import TestClient

from app.main import app
from app.database import open_project_session
from app import models


def _fresh_client():
    c = TestClient(app)
    c.headers.update({"Origin": "http://localhost:5173"})
    return c


def _make_case(auth_client, slug):
    """Creates a fresh suite -> published revision -> one case, returns test_case_id."""
    suite = auth_client.post(f"/api/{slug}/suites", json={"name": "WF Suite", "suite_type": "OTHER"}).json()
    revision = auth_client.post(f"/api/{slug}/suites/{suite['id']}/revisions", json={"revision_label": "wfv1"}).json()
    case = auth_client.post(
        f"/api/{slug}/revisions/{revision['id']}/cases",
        json={"checkpoint_code": "WF-001", "title": "wf case", "action_md": "do it", "expected_result_md": "it works"},
    ).json()
    auth_client.post(f"/api/{slug}/suites/{suite['id']}/revisions/{revision['id']}/publish")
    return case["id"]


def _all_step_type_payloads():
    """One minimally-valid payload per WORKFLOW_STEP_TYPES entry."""
    return [
        {"step_type": "NAVIGATE", "input_value": "https://example.com/login"},
        {"step_type": "CLICK", "locator_strategy": "ROLE", "locator_value": "button:Sign in"},
        {"step_type": "FILL", "locator_strategy": "LABEL", "locator_value": "Email", "input_value": "tester@example.com"},
        {"step_type": "SELECT", "locator_strategy": "LABEL", "locator_value": "Country", "input_value": "Thailand"},
        {"step_type": "CHECK", "locator_strategy": "LABEL", "locator_value": "Remember me"},
        {"step_type": "UNCHECK", "locator_strategy": "LABEL", "locator_value": "Newsletter"},
        {"step_type": "PRESS_KEY", "locator_strategy": "CSS", "locator_value": "body", "input_value": "Enter"},
        {"step_type": "WAIT_FOR_ELEMENT", "locator_strategy": "TEST_ID", "locator_value": "dashboard-root"},
        {"step_type": "ASSERT_VISIBLE", "locator_strategy": "ROLE", "locator_value": "heading:Dashboard"},
        {"step_type": "ASSERT_TEXT", "expected_value": "Welcome back"},
        {"step_type": "ASSERT_URL", "expected_value": "https://example.com/dashboard"},
        {"step_type": "SCREENSHOT"},
        {"step_type": "MANUAL_CHECKPOINT", "checkpoint_instructions": "Confirm the dashboard tiles look correct"},
    ]


def test_hyb1_full_acceptance_gate(auth_client, project_slug):
    slug = project_slug

    # 1. Create workflow definition.
    wf = auth_client.post(f"/api/{slug}/workflows", json={"name": "Login smoke", "description": "d"})
    assert wf.status_code == 200, wf.text
    workflow_id = wf.json()["id"]

    # 2. Create draft revision.
    rev = auth_client.post(f"/api/{slug}/workflows/{workflow_id}/revisions", json={"revision_label": "v1"})
    assert rev.status_code == 200, rev.text
    revision_id = rev.json()["id"]
    assert rev.json()["status"] == "DRAFT"

    # 3. Add all supported MVP step types.
    step_ids = []
    for payload in _all_step_type_payloads():
        r = auth_client.post(f"/api/{slug}/workflows/{workflow_id}/revisions/{revision_id}/steps", json=payload)
        assert r.status_code == 200, f"{payload['step_type']}: {r.text}"
        step_ids.append(r.json()["id"])
    assert len(step_ids) == 13

    # 4. Reorder steps (reverse order).
    reversed_ids = list(reversed(step_ids))
    r = auth_client.post(
        f"/api/{slug}/workflows/{workflow_id}/revisions/{revision_id}/steps/reorder",
        json={"step_ids_in_order": reversed_ids},
    )
    assert r.status_code == 200, r.text
    got_order = [s["id"] for s in r.json()]
    assert got_order == reversed_ids

    # 5. Manual checkpoint already configured above (last of the 13 step types);
    # confirm it persisted with instructions.
    steps = auth_client.get(f"/api/{slug}/workflows/{workflow_id}/revisions/{revision_id}/steps").json()
    checkpoint_steps = [s for s in steps if s["step_type"] == "MANUAL_CHECKPOINT"]
    assert len(checkpoint_steps) == 1
    assert checkpoint_steps[0]["checkpoint_instructions"]

    # 6. Configure a sensitive variable without persisting its real value.
    sensitive_ok = auth_client.post(
        f"/api/{slug}/workflows/{workflow_id}/revisions/{revision_id}/steps",
        json={
            "step_type": "FILL",
            "locator_strategy": "LABEL",
            "locator_value": "Password",
            "input_value": "${SECRET_LOGIN_PASSWORD}",
            "is_sensitive": True,
        },
    )
    assert sensitive_ok.status_code == 200, sensitive_ok.text
    assert sensitive_ok.json()["input_value"] == "${SECRET_LOGIN_PASSWORD}"
    # A literal value for a sensitive field must be rejected outright.
    sensitive_literal_rejected = auth_client.post(
        f"/api/{slug}/workflows/{workflow_id}/revisions/{revision_id}/steps",
        json={
            "step_type": "FILL",
            "locator_strategy": "LABEL",
            "locator_value": "Password",
            "input_value": "hunter2",
            "is_sensitive": True,
        },
    )
    assert sensitive_literal_rejected.status_code == 400
    assert "placeholder" in sensitive_literal_rejected.json()["detail"].lower()

    # 7. Link workflow to a test case.
    test_case_id = _make_case(auth_client, slug)
    link = auth_client.post(
        f"/api/{slug}/workflows/{workflow_id}/revisions/{revision_id}/links", json={"test_case_id": test_case_id}
    )
    assert link.status_code == 200, link.text
    assert link.json()["test_case_id"] == test_case_id
    assert link.json()["logical_case_key"]  # copied from the case at link time

    # 8. Publish revision.
    pub = auth_client.post(f"/api/{slug}/workflows/{workflow_id}/revisions/{revision_id}/publish")
    assert pub.status_code == 200, pub.text
    assert pub.json()["status"] == "PUBLISHED"

    # 9. Confirm published revision cannot be edited.
    blocked = auth_client.post(
        f"/api/{slug}/workflows/{workflow_id}/revisions/{revision_id}/steps",
        json={"step_type": "SCREENSHOT"},
    )
    assert blocked.status_code == 400
    assert "DRAFT" in blocked.json()["detail"]

    # 10. Clone it into a new draft.
    clone = auth_client.post(
        f"/api/{slug}/workflows/{workflow_id}/revisions/{revision_id}/clone",
        json={"revision_label": "v2", "change_summary": "correction"},
    )
    assert clone.status_code == 200, clone.text
    clone_id = clone.json()["id"]
    assert clone.json()["status"] == "DRAFT"
    assert clone.json()["supersedes_revision_id"] == revision_id

    clone_steps = auth_client.get(f"/api/{slug}/workflows/{workflow_id}/revisions/{clone_id}/steps").json()
    assert len(clone_steps) == len(steps) + 1  # +1 sensitive FILL step added in step 6
    clone_links = auth_client.get(f"/api/{slug}/workflows/{workflow_id}/revisions/{clone_id}/links").json()
    assert len(clone_links) == 1

    # 11. Confirm old revision remains unchanged (still PUBLISHED, same step count).
    old_steps_after = auth_client.get(f"/api/{slug}/workflows/{workflow_id}/revisions/{revision_id}/steps").json()
    assert len(old_steps_after) == len(steps) + 1
    old_rev_after = auth_client.get(f"/api/{slug}/workflows/{workflow_id}/revisions/{revision_id}").json()
    assert old_rev_after["status"] == "PUBLISHED"

    # Publishing the clone must supersede the original.
    pub2 = auth_client.post(f"/api/{slug}/workflows/{workflow_id}/revisions/{clone_id}/publish")
    assert pub2.status_code == 200, pub2.text
    superseded = auth_client.get(f"/api/{slug}/workflows/{workflow_id}/revisions/{revision_id}").json()
    assert superseded["status"] == "SUPERSEDED"

    # 12. Authorization boundaries.
    viewer_created = auth_client.post(
        "/api/auth/users", json={"email": "wf-viewer@example.com", "password": "ViewerPass123!", "role": "VIEWER"}
    )
    assert viewer_created.status_code == 200, viewer_created.text
    viewer = _fresh_client()
    viewer.post("/api/auth/login", json={"email": "wf-viewer@example.com", "password": "ViewerPass123!"})
    viewer.post("/api/auth/change-password", json={"current_password": "ViewerPass123!", "new_password": "ViewerPass456!"})

    viewer_read = viewer.get(f"/api/{slug}/workflows")
    assert viewer_read.status_code == 200, "VIEWER must be able to read workflows"
    viewer_write = viewer.post(f"/api/{slug}/workflows", json={"name": "should be rejected"})
    assert viewer_write.status_code == 403, "VIEWER must not be able to create a workflow"

    tester_created = auth_client.post(
        "/api/auth/users", json={"email": "wf-tester@example.com", "password": "TesterPass123!", "role": "TESTER"}
    )
    assert tester_created.status_code == 200, tester_created.text
    tester = _fresh_client()
    tester.post("/api/auth/login", json={"email": "wf-tester@example.com", "password": "TesterPass123!"})
    tester.post("/api/auth/change-password", json={"current_password": "TesterPass123!", "new_password": "TesterPass456!"})

    tester_wf = tester.post(f"/api/{slug}/workflows", json={"name": "tester wf"})
    assert tester_wf.status_code == 200
    tester_rev = tester.post(f"/api/{slug}/workflows/{tester_wf.json()['id']}/revisions", json={"revision_label": "v1"})
    assert tester_rev.status_code == 200
    tester_rev_id = tester_rev.json()["id"]
    tester.post(
        f"/api/{slug}/workflows/{tester_wf.json()['id']}/revisions/{tester_rev_id}/steps",
        json={"step_type": "SCREENSHOT"},
    )
    # Publishing is ADMIN-only -- a TESTER must not be able to publish.
    tester_publish = tester.post(f"/api/{slug}/workflows/{tester_wf.json()['id']}/revisions/{tester_rev_id}/publish")
    assert tester_publish.status_code == 403, "TESTER must not be able to publish a workflow revision"

    # 13. Confirm audit/activity records for the publish action.
    db = open_project_session(slug)
    try:
        rows = (
            db.query(models.ActivityLog)
            .filter(models.ActivityLog.entity_type == "workflow_revision", models.ActivityLog.entity_id == revision_id)
            .all()
        )
        assert any(r.new_value == "PUBLISHED" for r in rows), "publish must be recorded in ActivityLog"
        assert any(r.changed_by == "admin@example.com" for r in rows), "activity record must carry real actor identity"
    finally:
        db.close()


def test_delete_workflow_hides_it_but_keeps_history(auth_client, project_slug):
    slug = project_slug
    workflow = auth_client.post(f"/api/{slug}/workflows", json={"name": "delete from main screen"}).json()
    revision = auth_client.post(
        f"/api/{slug}/workflows/{workflow['id']}/revisions", json={"revision_label": "v1"}
    ).json()
    auth_client.post(
        f"/api/{slug}/workflows/{workflow['id']}/revisions/{revision['id']}/steps",
        json={"step_type": "SCREENSHOT"},
    )
    auth_client.post(f"/api/{slug}/workflows/{workflow['id']}/revisions/{revision['id']}/publish")

    deleted = auth_client.delete(f"/api/{slug}/workflows/{workflow['id']}")
    assert deleted.status_code == 204, deleted.text
    assert workflow["id"] not in [item["id"] for item in auth_client.get(f"/api/{slug}/workflows").json()]
    preserved = auth_client.get(f"/api/{slug}/workflows/{workflow['id']}/revisions")
    assert preserved.status_code == 200
    assert preserved.json()[0]["id"] == revision["id"]


def test_workflow_revision_label_must_be_unique_per_workflow(auth_client, project_slug):
    slug = project_slug
    wf = auth_client.post(f"/api/{slug}/workflows", json={"name": "dup test"}).json()
    auth_client.post(f"/api/{slug}/workflows/{wf['id']}/revisions", json={"revision_label": "v1"})
    dup = auth_client.post(f"/api/{slug}/workflows/{wf['id']}/revisions", json={"revision_label": "v1"})
    assert dup.status_code == 400


def test_cannot_publish_revision_with_no_enabled_steps(auth_client, project_slug):
    slug = project_slug
    wf = auth_client.post(f"/api/{slug}/workflows", json={"name": "empty wf"}).json()
    rev = auth_client.post(f"/api/{slug}/workflows/{wf['id']}/revisions", json={"revision_label": "v1"}).json()
    r = auth_client.post(f"/api/{slug}/workflows/{wf['id']}/revisions/{rev['id']}/publish")
    assert r.status_code == 400
    assert "no enabled steps" in r.json()["detail"]


def test_reorder_rejects_mismatched_step_id_set(auth_client, project_slug):
    slug = project_slug
    wf = auth_client.post(f"/api/{slug}/workflows", json={"name": "reorder test"}).json()
    rev = auth_client.post(f"/api/{slug}/workflows/{wf['id']}/revisions", json={"revision_label": "v1"}).json()
    auth_client.post(f"/api/{slug}/workflows/{wf['id']}/revisions/{rev['id']}/steps", json={"step_type": "SCREENSHOT"})
    r = auth_client.post(
        f"/api/{slug}/workflows/{wf['id']}/revisions/{rev['id']}/steps/reorder",
        json={"step_ids_in_order": [999999]},
    )
    assert r.status_code == 400
