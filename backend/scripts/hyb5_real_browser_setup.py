"""HYB-5 real headed-browser verification: setup script.

Builds a real project + a real >=50-step workflow that navigates the
REAL QA-Again frontend itself (the running Vite dev server), then
prints everything needed to run the real Node.js/TypeScript Playwright
runner (`npm run execute` in runner/) against it. Not committed data --
this only talks to a real running backend over HTTP.

The workflow:
  - real login (NAVIGATE, FILL email, FILL password [sensitive
    ${TARGET_PASSWORD} placeholder], CLICK "Sign in")
  - real CHECK/UNCHECK of the "Show archived" checkbox on the Projects
    page
  - real NAVIGATE into the created project's dashboard
  - three real laps around every nav tab (Dashboard/Test Suites/Test
    Cycles/Reports/Workflows/Hybrid Reports), each hop a real CLICK +
    ASSERT_URL + SCREENSHOT against the real rendered React app
  - a real SELECT on the Hybrid Reports page's workflow dropdown
  - a real MANUAL_CHECKPOINT mid-way
  - a final, deliberately failing ASSERT_TEXT step (v1) -- a genuine
    failure, not simulated -- and a cloned, corrected v2 revision for
    the deliberate-rerun/retry demonstration
"""
import json
import sys

import requests

BASE = "http://127.0.0.1:8000"
FRONTEND_BASE = "http://localhost:5173"
ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "changeme123"

session = requests.Session()
session.headers.update({"Origin": "http://localhost:5173"})


def login():
    r = session.post(f"{BASE}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    if r.status_code != 200:
        # Already rotated past the bootstrap password by an earlier
        # phase1 run in this same backend process.
        r = session.post(f"{BASE}/api/auth/login", json={"email": ADMIN_EMAIL, "password": "changeme456"})
        r.raise_for_status()
        return
    r.raise_for_status()
    session.post(f"{BASE}/api/auth/change-password", json={"current_password": ADMIN_PASSWORD, "new_password": "changeme456"})


def nav_lap(step_no_start, project_slug):
    """One lap of CLICK+ASSERT_URL+SCREENSHOT around every real nav tab."""
    tabs = [
        ("Test Suites", "suites"),
        ("Test Cycles", "cycles"),
        ("Reports", "reports"),
        ("Workflows", "workflows"),
        ("Hybrid Reports", "hybrid-reports"),
        ("Dashboard", "dashboard"),
    ]
    steps = []
    for label, path in tabs:
        # "Reports" and "Hybrid Reports" both match a substring/case-
        # insensitive getByRole(name=...) lookup (Playwright's default,
        # non-exact matching) -- exact CSS text matching avoids that
        # real ambiguity rather than relying on ROLE's substring default.
        steps.append({"step_type": "CLICK", "description": f"nav -> {label}", "locator_strategy": "CSS", "locator_value": f'nav :text-is("{label}")'})
        steps.append({"step_type": "ASSERT_URL", "description": f"assert url contains /{path}", "expected_value": f"/{path}"})
        steps.append({"step_type": "SCREENSHOT", "description": f"screenshot of {label}"})
    return steps


def build_steps(project_slug):
    steps = []
    steps.append({"step_type": "NAVIGATE", "description": "go to login", "input_value": "/login"})
    steps.append({"step_type": "FILL", "description": "fill email", "locator_strategy": "LABEL", "locator_value": "Email", "input_value": ADMIN_EMAIL})
    steps.append(
        {
            "step_type": "FILL",
            "description": "fill password (sensitive)",
            "locator_strategy": "LABEL",
            "locator_value": "Password",
            "input_value": "${TARGET_PASSWORD}",
            "is_sensitive": True,
        }
    )
    steps.append({"step_type": "CLICK", "description": "click Sign in", "locator_strategy": "ROLE", "locator_value": "button:Sign in"})
    steps.append({"step_type": "ASSERT_TEXT", "description": "assert Projects page loaded", "expected_value": "Projects"})
    steps.append({"step_type": "SCREENSHOT", "description": "screenshot of Projects page"})

    steps.append({"step_type": "CHECK", "description": "check Show archived", "locator_strategy": "LABEL", "locator_value": "Show archived"})
    steps.append({"step_type": "ASSERT_VISIBLE", "description": "assert checkbox still visible", "locator_strategy": "LABEL", "locator_value": "Show archived"})
    steps.append({"step_type": "UNCHECK", "description": "uncheck Show archived", "locator_strategy": "LABEL", "locator_value": "Show archived"})

    steps.append({"step_type": "NAVIGATE", "description": "go to project dashboard", "input_value": f"/{project_slug}/dashboard"})
    steps.append({"step_type": "ASSERT_URL", "description": "assert on project dashboard", "expected_value": f"/{project_slug}/dashboard"})
    steps.append({"step_type": "SCREENSHOT", "description": "screenshot of project dashboard"})

    # Lap 1
    steps += nav_lap(len(steps), project_slug)

    # Real SELECT against Hybrid Reports page's workflow dropdown (the
    # only <select> on that page -- unambiguous).
    steps.append({"step_type": "CLICK", "description": "nav -> Hybrid Reports (for select)", "locator_strategy": "CSS", "locator_value": 'nav :text-is("Hybrid Reports")'})
    steps.append({"step_type": "ASSERT_URL", "description": "assert url contains /hybrid-reports", "expected_value": "/hybrid-reports"})
    steps.append(
        {
            "step_type": "SELECT",
            "description": "select the demo workflow in the trend picker",
            "locator_strategy": "ROLE",
            "locator_value": "combobox",
            "input_value": "HYB Real Browser Verification Workflow",
        }
    )
    steps.append({"step_type": "SCREENSHOT", "description": "screenshot after selecting workflow"})

    # Manual checkpoint, mid-way.
    steps.append(
        {
            "step_type": "MANUAL_CHECKPOINT",
            "description": "human checkpoint mid-run",
            "checkpoint_instructions": "Confirm the Hybrid Reports page rendered correctly with the workflow selected before continuing.",
        }
    )

    # Lap 2 and lap 3 (post-resume -- same browser session).
    steps += nav_lap(len(steps), project_slug)
    steps += nav_lap(len(steps), project_slug)

    return steps


def build_failing_tail():
    return [{"step_type": "ASSERT_TEXT", "description": "DELIBERATE genuine failure -- text that does not exist", "expected_value": "ZZZ_THIS_TEXT_DOES_NOT_EXIST_ZZZ"}]


def build_passing_tail():
    return [{"step_type": "ASSERT_TEXT", "description": "corrected assertion -- real text on Dashboard", "expected_value": "Dashboard"}]


def phase1():
    """Creates the project/workflow/v1 (with the deliberate failing
    tail)/suite/cycle/runner token, publishes v1, and queues Run 1
    against it. v2 is NOT created yet -- publishing it would supersede
    v1 (immutable-revision discipline), and Run 1 must execute against
    v1 first."""
    login()
    project = session.post(f"{BASE}/api/projects", json={"name": "HYB-5 Real Browser Verification"}).json()
    slug = project["slug"]
    print(f"PROJECT_SLUG={slug}")

    wf = session.post(f"{BASE}/api/{slug}/workflows", json={"name": "HYB Real Browser Verification Workflow"}).json()
    rev1 = session.post(f"{BASE}/api/{slug}/workflows/{wf['id']}/revisions", json={"revision_label": "v1"}).json()

    all_steps = build_steps(slug) + build_failing_tail()
    print(f"Total steps in v1 (incl. deliberate failing tail): {len(all_steps)}")
    step_ids = []
    checkpoint_id = None
    for s in all_steps:
        r = session.post(f"{BASE}/api/{slug}/workflows/{wf['id']}/revisions/{rev1['id']}/steps", json=s)
        if r.status_code != 200:
            print(f"FAILED to create step {s}: {r.status_code} {r.text}", file=sys.stderr)
            sys.exit(1)
        body = r.json()
        step_ids.append(body["id"])
        if body["step_type"] == "MANUAL_CHECKPOINT":
            checkpoint_id = body["id"]

    pub1 = session.post(f"{BASE}/api/{slug}/workflows/{wf['id']}/revisions/{rev1['id']}/publish")
    pub1.raise_for_status()
    print(f"WORKFLOW_ID={wf['id']} REVISION_V1_ID={rev1['id']} STEP_COUNT={len(step_ids)} CHECKPOINT_STEP_ID={checkpoint_id}")

    suite = session.post(f"{BASE}/api/{slug}/suites", json={"name": "Real Browser Suite"}).json()
    suite_rev = session.post(f"{BASE}/api/{slug}/suites/{suite['id']}/revisions", json={"revision_label": "rv1"}).json()
    session.post(
        f"{BASE}/api/{slug}/revisions/{suite_rev['id']}/cases",
        json={"checkpoint_code": "REALBROWSER-001", "title": "c", "action_md": "a", "expected_result_md": "e"},
    )
    session.post(f"{BASE}/api/{slug}/suites/{suite['id']}/revisions/{suite_rev['id']}/publish")
    cycle = session.post(
        f"{BASE}/api/{slug}/cycles",
        json={
            "suite_id": suite["id"],
            "script_revision_id": suite_rev["id"],
            "name": "real browser cycle",
            "environment": "test",
            "target_base_url": FRONTEND_BASE,
        },
    ).json()
    result_id = session.get(f"{BASE}/api/{slug}/cycles/{cycle['id']}/results").json()[0]["id"]
    print(f"CYCLE_ID={cycle['id']} CYCLE_RESULT_ID={result_id} target_base_url={cycle.get('target_base_url')}")

    token_resp = session.post(f"{BASE}/api/runner-tokens", json={"label": "real-browser-verification-runner"})
    token_resp.raise_for_status()
    token = token_resp.json()["token"]
    print(f"RUNNER_TOKEN={token}")

    run1_resp = session.post(
        f"{BASE}/api/{slug}/workflow-runs", json={"workflow_revision_id": rev1["id"], "cycle_test_result_id": result_id}
    )
    if run1_resp.status_code != 200:
        print(f"FAILED to queue run 1: {run1_resp.status_code} {run1_resp.text}", file=sys.stderr)
        sys.exit(1)
    run1 = run1_resp.json()
    print(f"RUN_1_ID={run1['id']} (against v1, includes the deliberate failing tail)")

    print("\n--- runner/.env contents ---")
    print(f"BACKEND_BASE_URL={BASE}")
    print(f"PROJECT_SLUG={slug}")
    print(f"RUNNER_TOKEN={token}")
    print(f"TARGET_BASE_URL={FRONTEND_BASE}")
    print(f"TARGET_EMAIL={ADMIN_EMAIL}")
    print("TARGET_PASSWORD=changeme456")

    print(f"\nNEXT: run the real runner (npm run execute) against RUN_1_ID={run1['id']}.")
    print(f"Once it ends FAILED, run: python scripts/hyb5_real_browser_setup.py phase2 {slug} {wf['id']} {rev1['id']} {result_id}")


def phase2(slug, workflow_id, rev1_id, result_id):
    """Clones v1 -> v2 (drops the deliberate failing tail, adds the
    corrected assertion), publishes v2 (supersedes v1), and queues
    Run 2 against it -- the real deliberate-rerun-after-fix path."""
    login()
    clone = session.post(f"{BASE}/api/{slug}/workflows/{workflow_id}/revisions/{rev1_id}/clone", json={"revision_label": "v2-corrected"}).json()
    rev2_steps = session.get(f"{BASE}/api/{slug}/workflows/{workflow_id}/revisions/{clone['id']}/steps").json()
    rev2_steps.sort(key=lambda s: s["sequence_no"])
    last_step = rev2_steps[-1]
    assert last_step["description"].startswith("DELIBERATE"), last_step["description"]
    del_r = session.delete(f"{BASE}/api/{slug}/workflows/{workflow_id}/revisions/{clone['id']}/steps/{last_step['id']}")
    if del_r.status_code != 200:
        print(f"Could not delete failing tail step from v2: {del_r.status_code} {del_r.text}", file=sys.stderr)
        sys.exit(1)
    for s in build_passing_tail():
        session.post(f"{BASE}/api/{slug}/workflows/{workflow_id}/revisions/{clone['id']}/steps", json=s)
    pub2 = session.post(f"{BASE}/api/{slug}/workflows/{workflow_id}/revisions/{clone['id']}/publish")
    pub2.raise_for_status()
    print(f"REVISION_V2_CORRECTED_ID={clone['id']}")

    run2_resp = session.post(
        f"{BASE}/api/{slug}/workflow-runs", json={"workflow_revision_id": clone["id"], "cycle_test_result_id": result_id}
    )
    if run2_resp.status_code != 200:
        print(f"FAILED to queue run 2: {run2_resp.status_code} {run2_resp.text}", file=sys.stderr)
        sys.exit(1)
    run2 = run2_resp.json()
    print(f"RUN_2_ID={run2['id']} (deliberate rerun against corrected v2)")
    print("\nNEXT: run the real runner (npm run execute) again to execute Run 2.")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "phase2":
        phase2(sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5]))
    else:
        phase1()
