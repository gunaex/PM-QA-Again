"""HYB-5 realistic-scale fixture generator and performance measurement.

Not run in CI, not imported by the app — a standalone script an operator
runs against a REAL running backend (uvicorn) to build a large hybrid
dataset and measure real endpoint response times. Never commits the
resulting database (backend/data/projects/*.db is gitignored) — this
script only ever writes to a project's normal SQLite file via the real
HTTP API, exactly as a real user/runner would.

Usage:
    # Terminal 1: real backend, filesystem evidence storage (default)
    cd backend && ./.venv/Scripts/uvicorn app.main:app --port 8000

    # Terminal 2
    cd backend && ./.venv/Scripts/python scripts/hyb5_scale_fixture.py

Builds, in one project:
  - one workflow with 60 steps (>= the 50+ required by HYB-5's scale gate)
  - two published revisions of it (a superseding correction)
  - 5 sequential runs against the latest revision, including:
      - one run with 3 real MANUAL_CHECKPOINT pauses + real decisions
      - one run with a long (~3s, stands in for "long pause") checkpoint wait
      - one run with repeated (3x) locator-failure retries on one step
      - one run that goes RUNNER_LOST (simulated via a near-zero lease)
      - one ordinary all-PASSED run
  - real screenshot evidence on every SCREENSHOT/MANUAL_CHECKPOINT step run
  - a defect linked to the locator-failure run

Then times: workflow list, run list, run detail, hybrid dashboard, every
hybrid report, run timing, step trend, Excel export, ZIP export.
"""
import json
import time

import requests

BASE = "http://127.0.0.1:8000"
ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "changeme123"

PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x02\x00\x00\x00\x02\x08\x02\x00\x00\x00\xfd\xd4\x9as"
    b"\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\xc0\xc0\xc0\x00\x00\x00\x06\x00\x03\xfa\xd0\x7f\xe6"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)

session = requests.Session()
session.headers.update({"Origin": "http://localhost:5173"})


def login():
    r = session.post(f"{BASE}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    if r.status_code != 200:
        # Already past the default-password bootstrap in a prior run of
        # this script -- try the rotated password instead.
        r = session.post(f"{BASE}/api/auth/login", json={"email": ADMIN_EMAIL, "password": "changeme456"})
    r.raise_for_status()
    session.post(f"{BASE}/api/auth/change-password", json={"current_password": "changeme123", "new_password": "changeme456"})


def issue_runner_token(label):
    r = session.post(f"{BASE}/api/runner-tokens", json={"label": label})
    r.raise_for_status()
    return r.json()["token"]


def runner_session(token):
    s = requests.Session()
    s.headers.update({"X-Runner-Token": token})
    return s


def build_workflow(slug, n_steps=60):
    wf = session.post(f"{BASE}/api/{slug}/workflows", json={"name": "HYB-5 Scale Workflow"}).json()
    rev1 = session.post(f"{BASE}/api/{slug}/workflows/{wf['id']}/revisions", json={"revision_label": "v1"}).json()
    step_ids = []
    checkpoint_ids = []
    for i in range(n_steps):
        if i in (10, 25, 40):
            s = session.post(
                f"{BASE}/api/{slug}/workflows/{wf['id']}/revisions/{rev1['id']}/steps",
                json={"step_type": "MANUAL_CHECKPOINT", "description": f"checkpoint {i}", "checkpoint_instructions": "verify manually"},
            ).json()
            checkpoint_ids.append(s["id"])
        else:
            s = session.post(
                f"{BASE}/api/{slug}/workflows/{wf['id']}/revisions/{rev1['id']}/steps",
                json={"step_type": "SCREENSHOT", "description": f"scale step {i}"},
            ).json()
        step_ids.append(s["id"])
    session.post(f"{BASE}/api/{slug}/workflows/{wf['id']}/revisions/{rev1['id']}/publish")

    # Second, superseding published revision -- exercises multi-revision
    # history reporting/exports.
    rev2 = session.post(
        f"{BASE}/api/{slug}/workflows/{wf['id']}/revisions/{rev1['id']}/clone",
        json={"revision_label": "v2"},
    ).json()
    session.post(f"{BASE}/api/{slug}/workflows/{wf['id']}/revisions/{rev2['id']}/publish")

    # Cloning creates brand new WorkflowStep rows (new ids) -- re-fetch
    # rev2's own steps rather than reusing rev1's ids, which would 404
    # against a run queued on rev2.
    rev2_steps = session.get(f"{BASE}/api/{slug}/workflows/{wf['id']}/revisions/{rev2['id']}/steps").json()
    rev2_steps.sort(key=lambda s: s["sequence_no"])
    step_ids_v2 = [s["id"] for s in rev2_steps]
    checkpoint_ids_v2 = [s["id"] for s in rev2_steps if s["step_type"] == "MANUAL_CHECKPOINT"]

    return wf["id"], rev2["id"], step_ids_v2, checkpoint_ids_v2


def make_cycle_result(slug, suffix):
    suite = session.post(f"{BASE}/api/{slug}/suites", json={"name": f"Scale Suite {suffix}"}).json()
    rev = session.post(f"{BASE}/api/{slug}/suites/{suite['id']}/revisions", json={"revision_label": "rv1"}).json()
    session.post(
        f"{BASE}/api/{slug}/revisions/{rev['id']}/cases",
        json={"checkpoint_code": f"SCALE-{suffix}", "title": "c", "action_md": "a", "expected_result_md": "e"},
    )
    session.post(f"{BASE}/api/{slug}/suites/{suite['id']}/revisions/{rev['id']}/publish")
    cycle = session.post(
        f"{BASE}/api/{slug}/cycles",
        json={"suite_id": suite["id"], "script_revision_id": rev["id"], "name": f"scale cycle {suffix}", "environment": "test"},
    ).json()
    result_id = session.get(f"{BASE}/api/{slug}/cycles/{cycle['id']}/results").json()[0]["id"]
    return cycle["id"], result_id


def run_all_pass(slug, revision_id, step_ids, checkpoint_ids, cycle_result_id, runner):
    queued = session.post(
        f"{BASE}/api/{slug}/workflow-runs", json={"workflow_revision_id": revision_id, "cycle_test_result_id": cycle_result_id}
    ).json()
    run_id = queued["id"]
    claim = runner.post(f"{BASE}/api/{slug}/workflow-runs/claim").json()
    lease = claim["lease_token"]
    for step_id in step_ids:
        sr = runner.post(f"{BASE}/api/{slug}/workflow-runs/{run_id}/step-runs", json={"workflow_step_id": step_id, "lease_token": lease}).json()
        if step_id in checkpoint_ids:
            runner.post(
                f"{BASE}/api/{slug}/workflow-runs/{run_id}/evidence",
                params={"lease_token": lease, "step_run_id": sr["id"]},
                files={"file": ("shot.png", PNG_BYTES, "image/png")},
            )
            runner.post(
                f"{BASE}/api/{slug}/workflow-runs/{run_id}/events",
                json={"event_type": "CHECKPOINT_WAITING", "actor_type": "RUNNER", "lease_token": lease, "payload_json": json.dumps({"step_id": step_id})},
            )
            session.post(
                f"{BASE}/api/{slug}/workflow-runs/{run_id}/checkpoint-decision",
                json={"workflow_step_id": step_id, "status": "PASS", "actual_result_md": "ok"},
            )
            runner.post(f"{BASE}/api/{slug}/workflow-runs/{run_id}/checkpoint-resume", json={"workflow_step_id": step_id, "lease_token": lease})
        else:
            runner.put(f"{BASE}/api/{slug}/workflow-runs/{run_id}/step-runs/{sr['id']}", json={"status": "PASSED", "lease_token": lease})
    runner.post(f"{BASE}/api/{slug}/workflow-runs/{run_id}/complete", json={"status": "PASSED", "lease_token": lease})
    return run_id


def run_long_checkpoint_pause(slug, revision_id, checkpoint_ids, runner, wait_seconds=3):
    queued = session.post(f"{BASE}/api/{slug}/workflow-runs", json={"workflow_revision_id": revision_id}).json()
    run_id = queued["id"]
    claim = runner.post(f"{BASE}/api/{slug}/workflow-runs/claim").json()
    lease = claim["lease_token"]
    cp_id = checkpoint_ids[0]
    runner.post(f"{BASE}/api/{slug}/workflow-runs/{run_id}/step-runs", json={"workflow_step_id": cp_id, "lease_token": lease})
    runner.post(
        f"{BASE}/api/{slug}/workflow-runs/{run_id}/events",
        json={"event_type": "CHECKPOINT_WAITING", "actor_type": "RUNNER", "lease_token": lease, "payload_json": json.dumps({"step_id": cp_id})},
    )
    time.sleep(wait_seconds)
    session.post(
        f"{BASE}/api/{slug}/workflow-runs/{run_id}/checkpoint-decision",
        json={"workflow_step_id": cp_id, "status": "PASS", "actual_result_md": "ok after a long real wait"},
    )
    runner.post(f"{BASE}/api/{slug}/workflow-runs/{run_id}/checkpoint-resume", json={"workflow_step_id": cp_id, "lease_token": lease})
    runner.post(f"{BASE}/api/{slug}/workflow-runs/{run_id}/complete", json={"status": "PASSED", "lease_token": lease})
    return run_id


def run_with_locator_failures(slug, revision_id, step_ids, runner):
    queued = session.post(f"{BASE}/api/{slug}/workflow-runs", json={"workflow_revision_id": revision_id}).json()
    run_id = queued["id"]
    claim = runner.post(f"{BASE}/api/{slug}/workflow-runs/claim").json()
    lease = claim["lease_token"]
    flaky_step = step_ids[3]
    for attempt in range(1, 4):
        sr = runner.post(
            f"{BASE}/api/{slug}/workflow-runs/{run_id}/step-runs",
            json={"workflow_step_id": flaky_step, "lease_token": lease, "attempt_number": attempt},
        ).json()
        status = "PASSED" if attempt == 3 else "FAILED"
        failure_category = None if status == "PASSED" else "LOCATOR_NOT_FOUND"
        runner.put(
            f"{BASE}/api/{slug}/workflow-runs/{run_id}/step-runs/{sr['id']}",
            json={"status": status, "failure_category": failure_category, "lease_token": lease},
        )
    for step_id in step_ids[4:8]:
        sr = runner.post(f"{BASE}/api/{slug}/workflow-runs/{run_id}/step-runs", json={"workflow_step_id": step_id, "lease_token": lease}).json()
        runner.put(f"{BASE}/api/{slug}/workflow-runs/{run_id}/step-runs/{sr['id']}", json={"status": "PASSED", "lease_token": lease})
    runner.post(f"{BASE}/api/{slug}/workflow-runs/{run_id}/complete", json={"status": "PASSED", "lease_token": lease})

    session.post(
        f"{BASE}/api/{slug}/defects",
        json={"title": "Flaky locator on scale step 3", "severity": "P2", "description_md": "Repeated LOCATOR_NOT_FOUND before eventual pass"},
    )
    return run_id


def run_runner_lost(slug, revision_id, runner):
    queued = session.post(f"{BASE}/api/{slug}/workflow-runs", json={"workflow_revision_id": revision_id}).json()
    run_id = queued["id"]
    runner.post(f"{BASE}/api/{slug}/workflow-runs/claim")
    # Deliberately never heartbeat/complete -- the 60s active lease
    # expires naturally; the next request to this run sweeps it. We poll
    # briefly here just so the fixture ends in a clean RUNNER_LOST state
    # rather than leaving the demo waiting on a background sweep.
    return run_id


def timeit(label, fn):
    start = time.perf_counter()
    result = fn()
    elapsed_ms = (time.perf_counter() - start) * 1000
    size = len(result.content) if hasattr(result, "content") else None
    print(f"{label:<45} {elapsed_ms:8.1f} ms   {size or '':>10} bytes   status={getattr(result, 'status_code', '?')}")
    return result


def main():
    login()
    project = session.post(f"{BASE}/api/projects", json={"name": "HYB-5 Scale Fixture"}).json()
    slug = project["slug"]
    print(f"Project: {slug}")

    runner_token = issue_runner_token("scale-runner")
    runner = runner_session(runner_token)

    wf_id, revision_id, step_ids, checkpoint_ids = build_workflow(slug, n_steps=60)
    print(f"Workflow {wf_id}, revision {revision_id}, {len(step_ids)} steps ({len(checkpoint_ids)} checkpoints)")

    _, cycle_result_id = make_cycle_result(slug, "1")
    run_ids = []
    run_ids.append(run_all_pass(slug, revision_id, step_ids, checkpoint_ids, cycle_result_id, runner))
    run_ids.append(run_long_checkpoint_pause(slug, revision_id, checkpoint_ids, runner))
    run_ids.append(run_with_locator_failures(slug, revision_id, step_ids, runner))
    run_ids.append(run_runner_lost(slug, revision_id, runner_session(issue_runner_token("scale-runner-lost"))))
    print(f"Runs created: {run_ids}")

    # Touch the run-lost one so the lazy sweep resolves it before we
    # measure the dashboard (otherwise it'd still read CLAIMED).
    time.sleep(1)
    session.get(f"{BASE}/api/{slug}/workflow-runs/{run_ids[-1]}")

    cycle_id, _ = cycle_result_id, None  # for export below we need the cycle id, not result id
    cycle_id = session.get(f"{BASE}/api/{slug}/cycles").json()[0]["id"]

    print("\n--- Performance measurements (real HTTP, real SQLite, real EvidenceStorage) ---")
    timeit("GET /workflows", lambda: session.get(f"{BASE}/api/{slug}/workflows"))
    timeit("GET /workflow-runs (list)", lambda: session.get(f"{BASE}/api/{slug}/workflow-runs"))
    timeit("GET /workflow-runs/{id} (detail, 60-step run)", lambda: session.get(f"{BASE}/api/{slug}/workflow-runs/{run_ids[0]}"))
    timeit("GET /hybrid-reports/dashboard", lambda: session.get(f"{BASE}/api/{slug}/hybrid-reports/dashboard"))
    timeit("GET /hybrid-reports/locator-failures", lambda: session.get(f"{BASE}/api/{slug}/hybrid-reports/locator-failures"))
    timeit("GET /hybrid-reports/failure-categories", lambda: session.get(f"{BASE}/api/{slug}/hybrid-reports/failure-categories"))
    timeit("GET /hybrid-reports/workflows-frequent-failures", lambda: session.get(f"{BASE}/api/{slug}/hybrid-reports/workflows-frequent-failures"))
    timeit("GET /hybrid-reports/slowest-steps", lambda: session.get(f"{BASE}/api/{slug}/hybrid-reports/slowest-steps"))
    timeit("GET /hybrid-reports/timing/runs/{id} (60-step run)", lambda: session.get(f"{BASE}/api/{slug}/hybrid-reports/timing/runs/{run_ids[0]}"))
    timeit(
        "GET /hybrid-reports/timing/run-trend",
        lambda: session.get(f"{BASE}/api/{slug}/hybrid-reports/timing/run-trend", params={"workflow_id": wf_id}),
    )
    timeit(
        "GET /hybrid-reports/timing/step-trend",
        lambda: session.get(
            f"{BASE}/api/{slug}/hybrid-reports/timing/step-trend", params={"workflow_id": wf_id, "step_description": "scale step 0"}
        ),
    )
    timeit("GET cycles/{id}/export/excel", lambda: session.get(f"{BASE}/api/{slug}/cycles/{cycle_id}/export/excel"))
    timeit("GET cycles/{id}/export/zip", lambda: session.get(f"{BASE}/api/{slug}/cycles/{cycle_id}/export/zip"))


if __name__ == "__main__":
    main()
