"""Quick Manual Test entry flow acceptance gate -- verified against the
real running app (TestClient). Confirms atomic creation reuses the
exact existing domain objects (TestSuite/ScriptRevision/TestCase/
TestCycle/CycleTestResult), preserves evidence-required-for-PASS/
locked-cycle/append-only-history invariants, and that quick-test
artifacts are hidden-by-default but fully auditable/exportable."""
from fastapi.testclient import TestClient

from app.main import app

PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x02\x00\x00\x00\x02\x08\x02\x00\x00\x00\xfd\xd4\x9as"
    b"\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\xc0\xc0\xc0\x00\x00\x00\x06\x00\x03\xfa\xd0\x7f\xe6"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


def test_quick_test_creates_real_domain_objects_and_returns_execution_url(auth_client, project_slug):
    slug = project_slug
    r = auth_client.post(f"/api/{slug}/quick-test", json={"title": "Login works with valid credentials"})
    assert r.status_code == 200, r.text
    body = r.json()
    cycle = body["cycle"]
    result_id = body["result_id"]
    assert cycle["status"] == "READY"
    assert cycle["is_system_generated"] is True

    # Real CycleTestResult, immediately fetchable via the existing endpoint.
    result = auth_client.get(f"/api/{slug}/cycles/{cycle['id']}/results/{result_id}").json()
    assert result["status"] == "NOT_RUN"
    assert result["case_title"] == "Login works with valid credentials"

    # Real, real published ScriptRevision underneath -- fetchable via the
    # existing suite/revision endpoints (not a parallel model).
    suites = auth_client.get(f"/api/{slug}/suites", params={"include_system_generated": True}).json()
    quick_suite = next(s for s in suites if s["is_system_generated"])
    revisions = auth_client.get(f"/api/{slug}/suites/{quick_suite['id']}/revisions").json()
    assert any(rev["id"] == cycle["script_revision_id"] and rev["status"] == "PUBLISHED" for rev in revisions)


def test_quick_test_hidden_from_default_lists_but_auditable(auth_client, project_slug):
    slug = project_slug
    r = auth_client.post(f"/api/{slug}/quick-test", json={"title": "Hidden by default check"})
    cycle_id = r.json()["cycle"]["id"]

    default_suites = auth_client.get(f"/api/{slug}/suites").json()
    assert not any(s["is_system_generated"] for s in default_suites)
    default_cycles = auth_client.get(f"/api/{slug}/cycles").json()
    assert not any(c["id"] == cycle_id for c in default_cycles)

    shown_cycles = auth_client.get(f"/api/{slug}/cycles", params={"include_system_generated": True}).json()
    assert any(c["id"] == cycle_id for c in shown_cycles)

    # Fully auditable/exportable regardless of the UI-list hiding: the
    # cycle is a real row, reachable directly by id and via export.
    direct = auth_client.get(f"/api/{slug}/cycles/{cycle_id}").json()
    assert direct["id"] == cycle_id
    excel = auth_client.get(f"/api/{slug}/cycles/{cycle_id}/export/excel")
    assert excel.status_code == 200


def test_quick_test_defaults_environment_to_most_recently_used(auth_client, project_slug):
    slug = project_slug
    suite = auth_client.post(f"/api/{slug}/suites", json={"name": "Env Suite"}).json()
    rev = auth_client.post(f"/api/{slug}/suites/{suite['id']}/revisions", json={"revision_label": "v1"}).json()
    auth_client.post(f"/api/{slug}/revisions/{rev['id']}/cases", json={"checkpoint_code": "ENV-1", "title": "c", "action_md": "a", "expected_result_md": "e"})
    auth_client.post(f"/api/{slug}/suites/{suite['id']}/revisions/{rev['id']}/publish")
    auth_client.post(f"/api/{slug}/cycles", json={"suite_id": suite["id"], "script_revision_id": rev["id"], "name": "env cycle", "environment": "staging-custom-env"})

    r = auth_client.post(f"/api/{slug}/quick-test", json={"title": "Environment default check"})
    assert r.json()["cycle"]["environment"] == "staging-custom-env"


def test_quick_test_evidence_required_for_pass_still_enforced(auth_client, project_slug):
    slug = project_slug
    body = auth_client.post(f"/api/{slug}/quick-test", json={"title": "Evidence gate check"}).json()
    cycle_id, result_id = body["cycle"]["id"], body["result_id"]

    blocked = auth_client.put(f"/api/{slug}/cycles/{cycle_id}/results/{result_id}", json={"status": "PASS", "actual_result_md": "ok"})
    assert blocked.status_code == 400
    assert "evidence" in blocked.json()["detail"].lower()

    auth_client.post(f"/api/{slug}/cycles/{cycle_id}/results/{result_id}/evidence", files={"file": ("shot.png", PNG_BYTES, "image/png")})
    passed = auth_client.put(f"/api/{slug}/cycles/{cycle_id}/results/{result_id}", json={"status": "PASS", "actual_result_md": "ok"})
    assert passed.status_code == 200
    assert passed.json()["status"] == "PASS"


def test_quick_test_evidence_required_for_pass_can_be_disabled(auth_client, project_slug):
    slug = project_slug
    body = auth_client.post(f"/api/{slug}/quick-test", json={"title": "No evidence required", "require_evidence_for_pass": False}).json()
    cycle_id, result_id = body["cycle"]["id"], body["result_id"]
    passed = auth_client.put(f"/api/{slug}/cycles/{cycle_id}/results/{result_id}", json={"status": "PASS", "actual_result_md": "ok"})
    assert passed.status_code == 200


def test_run_now_creates_and_opens_cycle_from_published_suite(auth_client, project_slug):
    slug = project_slug
    suite = auth_client.post(f"/api/{slug}/suites", json={"name": "Run Now Suite"}).json()
    rev = auth_client.post(f"/api/{slug}/suites/{suite['id']}/revisions", json={"revision_label": "v1"}).json()
    auth_client.post(f"/api/{slug}/revisions/{rev['id']}/cases", json={"checkpoint_code": "RN-1", "title": "c", "action_md": "a", "expected_result_md": "e"})
    auth_client.post(f"/api/{slug}/suites/{suite['id']}/revisions/{rev['id']}/publish")

    r = auth_client.post(f"/api/{slug}/suites/{suite['id']}/revisions/{rev['id']}/run-now", json={})
    assert r.status_code == 200, r.text
    cycle = r.json()
    assert cycle["status"] == "READY"
    assert suite["name"] in cycle["name"]
    results = auth_client.get(f"/api/{slug}/cycles/{cycle['id']}/results").json()
    assert len(results) == 1


def test_run_now_rejects_draft_revision(auth_client, project_slug):
    slug = project_slug
    suite = auth_client.post(f"/api/{slug}/suites", json={"name": "Draft Run Now Suite"}).json()
    rev = auth_client.post(f"/api/{slug}/suites/{suite['id']}/revisions", json={"revision_label": "v1"}).json()
    r = auth_client.post(f"/api/{slug}/suites/{suite['id']}/revisions/{rev['id']}/run-now", json={})
    assert r.status_code == 400


def _make_cycle_with_results(auth_client, slug, n_cases=3):
    suite = auth_client.post(f"/api/{slug}/suites", json={"name": f"Rerun Suite {n_cases}"}).json()
    rev = auth_client.post(f"/api/{slug}/suites/{suite['id']}/revisions", json={"revision_label": "v1"}).json()
    case_ids = []
    for i in range(n_cases):
        c = auth_client.post(f"/api/{slug}/revisions/{rev['id']}/cases", json={"checkpoint_code": f"RR-{i}", "title": f"case {i}", "action_md": "a", "expected_result_md": "e"}).json()
        case_ids.append(c["id"])
    auth_client.post(f"/api/{slug}/suites/{suite['id']}/revisions/{rev['id']}/publish")
    cycle = auth_client.post(f"/api/{slug}/cycles", json={"suite_id": suite["id"], "script_revision_id": rev["id"], "name": "source cycle", "environment": "test", "require_evidence_for_pass": False}).json()
    results = auth_client.get(f"/api/{slug}/cycles/{cycle['id']}/results").json()
    return cycle, results, case_ids


def test_rerun_entire_cycle_creates_separate_historical_cycle(auth_client, project_slug):
    slug = project_slug
    cycle, results, _ = _make_cycle_with_results(auth_client, slug, n_cases=2)
    auth_client.put(f"/api/{slug}/cycles/{cycle['id']}/results/{results[0]['id']}", json={"status": "PASS", "actual_result_md": "ok"})

    r = auth_client.post(f"/api/{slug}/cycles/{cycle['id']}/rerun", json={"mode": "all"})
    assert r.status_code == 200, r.text
    new_cycle = r.json()
    assert new_cycle["id"] != cycle["id"]
    new_results = auth_client.get(f"/api/{slug}/cycles/{new_cycle['id']}/results").json()
    assert len(new_results) == 2
    assert all(nr["status"] == "NOT_RUN" for nr in new_results)

    # Source cycle is completely untouched.
    source_after = auth_client.get(f"/api/{slug}/cycles/{cycle['id']}/results/{results[0]['id']}").json()
    assert source_after["status"] == "PASS"


def test_rerun_fail_blocked_only(auth_client, project_slug):
    slug = project_slug
    cycle, results, _ = _make_cycle_with_results(auth_client, slug, n_cases=3)
    auth_client.put(f"/api/{slug}/cycles/{cycle['id']}/results/{results[0]['id']}", json={"status": "PASS", "actual_result_md": "ok"})
    auth_client.put(f"/api/{slug}/cycles/{cycle['id']}/results/{results[1]['id']}", json={"status": "FAIL", "actual_result_md": "broke"})
    auth_client.put(f"/api/{slug}/cycles/{cycle['id']}/results/{results[2]['id']}", json={"status": "BLOCKED", "blocked_reason": "env down"})

    r = auth_client.post(f"/api/{slug}/cycles/{cycle['id']}/rerun", json={"mode": "fail_blocked"})
    assert r.status_code == 200, r.text
    new_results = auth_client.get(f"/api/{slug}/cycles/{r.json()['id']}/results").json()
    assert len(new_results) == 2  # only the FAIL + BLOCKED cases, not the PASS one


def test_rerun_fail_blocked_with_no_failures_is_rejected(auth_client, project_slug):
    slug = project_slug
    cycle, results, _ = _make_cycle_with_results(auth_client, slug, n_cases=1)
    auth_client.put(f"/api/{slug}/cycles/{cycle['id']}/results/{results[0]['id']}", json={"status": "PASS", "actual_result_md": "ok"})
    r = auth_client.post(f"/api/{slug}/cycles/{cycle['id']}/rerun", json={"mode": "fail_blocked"})
    assert r.status_code == 400


def test_rerun_selected_cases(auth_client, project_slug):
    slug = project_slug
    cycle, results, case_ids = _make_cycle_with_results(auth_client, slug, n_cases=3)
    r = auth_client.post(f"/api/{slug}/cycles/{cycle['id']}/rerun", json={"mode": "selected", "case_ids": [case_ids[0]]})
    assert r.status_code == 200, r.text
    new_results = auth_client.get(f"/api/{slug}/cycles/{r.json()['id']}/results").json()
    assert len(new_results) == 1


def test_rerun_preserves_locked_cycle_rules_and_history(auth_client, project_slug):
    """Rerun creates a NEW cycle -- it must never let a locked source
    cycle's results be mutated, and every mutation on the new cycle
    still goes through the same append-only history mechanism."""
    slug = project_slug
    cycle, results, _ = _make_cycle_with_results(auth_client, slug, n_cases=1)
    auth_client.put(f"/api/{slug}/cycles/{cycle['id']}/results/{results[0]['id']}", json={"status": "FAIL", "actual_result_md": "broke"})
    r = auth_client.post(f"/api/{slug}/cycles/{cycle['id']}/rerun", json={"mode": "fail_blocked"})
    new_cycle_id = r.json()["id"]

    lock = auth_client.post(f"/api/{slug}/cycles/{cycle['id']}/lock")
    assert lock.status_code == 200
    still_locked_mutation = auth_client.put(f"/api/{slug}/cycles/{cycle['id']}/results/{results[0]['id']}", json={"status": "PASS", "actual_result_md": "x"})
    assert still_locked_mutation.status_code == 400

    # The new (rerun) cycle is a separate, unlocked cycle and works normally.
    new_results = auth_client.get(f"/api/{slug}/cycles/{new_cycle_id}/results").json()
    upd = auth_client.put(f"/api/{slug}/cycles/{new_cycle_id}/results/{new_results[0]['id']}", json={"status": "PASS", "actual_result_md": "ok"})
    assert upd.status_code == 200
    history = auth_client.get(f"/api/{slug}/cycles/{new_cycle_id}/results/{new_results[0]['id']}/history").json()
    assert len(history) == 1
    assert history[0]["status"] == "PASS"


def test_continue_last_test_returns_correct_cycle_and_result(auth_client, project_slug):
    slug = project_slug
    body = auth_client.post(f"/api/{slug}/quick-test", json={"title": "Continue test target"}).json()
    cycle_id, result_id = body["cycle"]["id"], body["result_id"]
    # Nudge the cycle into IN_PROGRESS (matches existing "first real
    # execution" convenience rule) with a real, evidence-satisfied PASS.
    auth_client.post(f"/api/{slug}/cycles/{cycle_id}/results/{result_id}/evidence", files={"file": ("s.png", PNG_BYTES, "image/png")})
    auth_client.put(f"/api/{slug}/cycles/{cycle_id}/results/{result_id}", json={"status": "PASS", "actual_result_md": "ok"})

    r = auth_client.get(f"/api/{slug}/continue-last-test")
    assert r.status_code == 200, r.text
    assert r.json()["cycle_id"] == cycle_id
    assert r.json()["result_id"] == result_id
