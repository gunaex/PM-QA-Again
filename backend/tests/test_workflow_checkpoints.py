"""HYB-4 acceptance gate (docs/Autonomous hybird prompt.md's HYB-4
section) verified against the real running app (TestClient), extending
HYB-2's already-proven claim/heartbeat/step-run/evidence protocol with
the human-decision resume half. Critical invariant under test throughout:
a human FAIL/BLOCKED/NOT_APPLICABLE decision is terminal and can never be
overwritten or converted to PASS by later automation or a racing
request."""
import time

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


def _make_workflow_with_checkpoint(auth_client, slug, instructions="verify the thing manually"):
    wf = auth_client.post(f"/api/{slug}/workflows", json={"name": "checkpoint test wf"}).json()
    rev = auth_client.post(f"/api/{slug}/workflows/{wf['id']}/revisions", json={"revision_label": "v1"}).json()
    pre = auth_client.post(
        f"/api/{slug}/workflows/{wf['id']}/revisions/{rev['id']}/steps",
        json={"step_type": "SCREENSHOT", "description": "pre-checkpoint automated step"},
    ).json()
    cp = auth_client.post(
        f"/api/{slug}/workflows/{wf['id']}/revisions/{rev['id']}/steps",
        json={"step_type": "MANUAL_CHECKPOINT", "description": "checkpoint", "checkpoint_instructions": instructions},
    ).json()
    post = auth_client.post(
        f"/api/{slug}/workflows/{wf['id']}/revisions/{rev['id']}/steps",
        json={"step_type": "SCREENSHOT", "description": "post-checkpoint automated step"},
    ).json()
    pub = auth_client.post(f"/api/{slug}/workflows/{wf['id']}/revisions/{rev['id']}/publish")
    assert pub.status_code == 200, pub.text
    return wf["id"], rev["id"], pre["id"], cp["id"], post["id"]


def _make_cycle_result(auth_client, slug, suffix=""):
    suite = auth_client.post(f"/api/{slug}/suites", json={"name": f"Checkpoint Suite{suffix}"}).json()
    revision = auth_client.post(f"/api/{slug}/suites/{suite['id']}/revisions", json={"revision_label": "rv1"}).json()
    auth_client.post(
        f"/api/{slug}/revisions/{revision['id']}/cases",
        json={"checkpoint_code": f"CKPT-001{suffix}", "title": "c", "action_md": "a", "expected_result_md": "e"},
    )
    auth_client.post(f"/api/{slug}/suites/{suite['id']}/revisions/{revision['id']}/publish")
    cycle = auth_client.post(
        f"/api/{slug}/cycles",
        json={"suite_id": suite["id"], "script_revision_id": revision["id"], "name": f"checkpoint cycle{suffix}", "environment": "test"},
    ).json()
    results = auth_client.get(f"/api/{slug}/cycles/{cycle['id']}/results").json()
    return cycle["id"], results[0]["id"]


def _issue_runner_token(auth_client, label):
    r = auth_client.post("/api/runner-tokens", json={"label": label})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _drive_to_checkpoint(auth_client, slug, suffix=""):
    """Publishes a workflow with an automated step, a MANUAL_CHECKPOINT,
    and another automated step; queues a run against a real cycle
    result; claims it with a real runner-token client; executes the
    pre-checkpoint step; creates the checkpoint's own step-run (mirroring
    what the real Playwright runner does before pausing -- see
    runner/src/execution/executor.ts); uploads a RUNNER screenshot for
    it; and posts CHECKPOINT_WAITING. Returns everything a test needs to
    drive the human-decision side."""
    wf_id, rev_id, pre_id, cp_id, post_id = _make_workflow_with_checkpoint(auth_client, slug)
    cycle_id, result_id = _make_cycle_result(auth_client, slug, suffix)
    queued = auth_client.post(
        f"/api/{slug}/workflow-runs", json={"workflow_revision_id": rev_id, "cycle_test_result_id": result_id}
    ).json()
    run_id = queued["id"]

    token = _issue_runner_token(auth_client, f"checkpoint-runner{suffix}")
    runner = _fresh_client()
    runner.headers.update({"X-Runner-Token": token})
    claim = runner.post(f"/api/{slug}/workflow-runs/claim").json()
    lease_token = claim["lease_token"]
    assert len(claim["steps"]) == 3

    sr_pre = runner.post(f"/api/{slug}/workflow-runs/{run_id}/step-runs", json={"workflow_step_id": pre_id, "lease_token": lease_token}).json()
    fin = runner.put(f"/api/{slug}/workflow-runs/{run_id}/step-runs/{sr_pre['id']}", json={"status": "PASSED", "lease_token": lease_token})
    assert fin.status_code == 200

    sr_cp = runner.post(f"/api/{slug}/workflow-runs/{run_id}/step-runs", json={"workflow_step_id": cp_id, "lease_token": lease_token}).json()
    upload = runner.post(
        f"/api/{slug}/workflow-runs/{run_id}/evidence",
        params={"lease_token": lease_token, "step_run_id": sr_cp["id"]},
        files={"file": ("checkpoint.png", PNG_BYTES, "image/png")},
    )
    assert upload.status_code == 200, upload.text
    screenshot = upload.json()
    assert screenshot["evidence_source"] == "RUNNER"

    ev = runner.post(
        f"/api/{slug}/workflow-runs/{run_id}/events",
        json={"event_type": "CHECKPOINT_WAITING", "actor_type": "RUNNER", "lease_token": lease_token, "payload_json": f'{{"step_id":{cp_id}}}'},
    )
    assert ev.status_code == 200, ev.text

    detail = auth_client.get(f"/api/{slug}/workflow-runs/{run_id}").json()
    assert detail["status"] == "WAITING_FOR_HUMAN"
    assert detail["checkpoint_waiting_since"] is not None

    return {
        "run_id": run_id,
        "cycle_id": cycle_id,
        "result_id": result_id,
        "pre_id": pre_id,
        "cp_id": cp_id,
        "post_id": post_id,
        "runner": runner,
        "lease_token": lease_token,
        "screenshot_id": screenshot["id"],
    }


def test_hyb4_checkpoint_pass_resume_full_flow(auth_client, project_slug):
    slug = project_slug
    ctx = _drive_to_checkpoint(auth_client, slug, suffix="-pass")
    run_id, cp_id, post_id = ctx["run_id"], ctx["cp_id"], ctx["post_id"]
    runner, lease_token = ctx["runner"], ctx["lease_token"]

    # Runner keeps heartbeating (and its lease alive) while paused.
    hb = runner.post(f"/api/{slug}/workflow-runs/{run_id}/heartbeat", json={"lease_token": lease_token})
    assert hb.status_code == 200
    assert hb.json()["status"] == "WAITING_FOR_HUMAN"

    # The human checkpoint review UI's single context call.
    checkpoint = auth_client.get(f"/api/{slug}/workflow-runs/{run_id}/checkpoint", params={"workflow_step_id": cp_id})
    assert checkpoint.status_code == 200, checkpoint.text
    body = checkpoint.json()
    assert body["checkpoint_instructions"] == "verify the thing manually"
    assert body["elapsed_waiting_seconds"] is not None
    assert body["run"]["step_runs"][0]["status"] == "PASSED"  # prior automated step result visible

    # Human PASS with real actor identity + timestamp (server-derived).
    decide = auth_client.post(
        f"/api/{slug}/workflow-runs/{run_id}/checkpoint-decision",
        json={"workflow_step_id": cp_id, "status": "PASS", "actual_result_md": "looks correct", "evidence_ids": [ctx["screenshot_id"]]},
    )
    assert decide.status_code == 200, decide.text
    decision = decide.json()
    assert decision["source"] == "HUMAN"
    assert decision["resume_authorized"] is True
    assert decision["decided_by_email"] == "admin@example.com"

    run_after = auth_client.get(f"/api/{slug}/workflow-runs/{run_id}").json()
    assert run_after["status"] == "RESUMING"

    # Evidence link was recorded server-side.
    evidence_after = auth_client.get(f"/api/{slug}/cycles/{ctx['cycle_id']}/results/{ctx['result_id']}/evidence/{ctx['screenshot_id']}").json()
    assert evidence_after["checkpoint_decision_id"] == decision["id"]

    # Runner resumes the *same* lease/browser session.
    resume = runner.post(f"/api/{slug}/workflow-runs/{run_id}/checkpoint-resume", json={"workflow_step_id": cp_id, "lease_token": lease_token})
    assert resume.status_code == 200, resume.text
    resumed = resume.json()
    assert resumed["run"]["status"] == "RUNNING"
    assert [s["id"] for s in resumed["steps"]] == [post_id]
    assert resumed["decision"]["status"] == "PASS"

    # Duplicate resume call from the same runner is idempotent, not an error.
    resume2 = runner.post(f"/api/{slug}/workflow-runs/{run_id}/checkpoint-resume", json={"workflow_step_id": cp_id, "lease_token": lease_token})
    assert resume2.status_code == 200

    sr_post = runner.post(f"/api/{slug}/workflow-runs/{run_id}/step-runs", json={"workflow_step_id": post_id, "lease_token": lease_token}).json()
    runner.put(f"/api/{slug}/workflow-runs/{run_id}/step-runs/{sr_post['id']}", json={"status": "PASSED", "lease_token": lease_token})
    complete = runner.post(f"/api/{slug}/workflow-runs/{run_id}/complete", json={"status": "PASSED", "lease_token": lease_token})
    assert complete.status_code == 200, complete.text
    assert complete.json()["status"] == "PASSED"

    final = auth_client.get(f"/api/{slug}/workflow-runs/{run_id}").json()
    assert any(e["event_type"] == "CHECKPOINT_DECIDED" and e["actor_type"] == "HUMAN" for e in final["events"])
    assert any(e["event_type"] == "RUN_RESUMED" and e["actor_type"] == "RUNNER" for e in final["events"])

    decisions = auth_client.get(f"/api/{slug}/workflow-runs/{run_id}/checkpoint-decisions").json()
    assert len(decisions) == 1
    assert decisions[0]["status"] == "PASS"
    assert decisions[0]["source"] == "HUMAN"


def test_hyb4_pass_requires_evidence_when_cycle_policy_demands_it(auth_client, project_slug):
    slug = project_slug
    wf_id, rev_id, pre_id, cp_id, post_id = _make_workflow_with_checkpoint(auth_client, slug)
    cycle_id, result_id = _make_cycle_result(auth_client, slug, suffix="-noev")
    queued = auth_client.post(f"/api/{slug}/workflow-runs", json={"workflow_revision_id": rev_id, "cycle_test_result_id": result_id}).json()
    run_id = queued["id"]
    token = _issue_runner_token(auth_client, "noev-runner")
    runner = _fresh_client()
    runner.headers.update({"X-Runner-Token": token})
    lease_token = runner.post(f"/api/{slug}/workflow-runs/claim").json()["lease_token"]
    runner.post(f"/api/{slug}/workflow-runs/{run_id}/step-runs", json={"workflow_step_id": pre_id, "lease_token": lease_token})
    runner.post(
        f"/api/{slug}/workflow-runs/{run_id}/events",
        json={"event_type": "CHECKPOINT_WAITING", "actor_type": "RUNNER", "lease_token": lease_token},
    )

    # No evidence uploaded for this checkpoint occurrence -- PASS must be rejected.
    decide = auth_client.post(
        f"/api/{slug}/workflow-runs/{run_id}/checkpoint-decision",
        json={"workflow_step_id": cp_id, "status": "PASS"},
    )
    assert decide.status_code == 400
    assert "evidence" in decide.json()["detail"].lower()


def test_hyb4_fail_decision_is_terminal_and_cannot_be_overwritten(auth_client, project_slug):
    slug = project_slug
    ctx = _drive_to_checkpoint(auth_client, slug, suffix="-fail")
    run_id, cp_id = ctx["run_id"], ctx["cp_id"]
    runner, lease_token = ctx["runner"], ctx["lease_token"]

    decide = auth_client.post(
        f"/api/{slug}/workflow-runs/{run_id}/checkpoint-decision",
        json={"workflow_step_id": cp_id, "status": "FAIL", "actual_result_md": "the button was missing"},
    )
    assert decide.status_code == 200, decide.text
    assert decide.json()["resume_authorized"] is False

    run_after = auth_client.get(f"/api/{slug}/workflow-runs/{run_id}").json()
    assert run_after["status"] == "FAILED"

    # The runner cannot resume a FAILed checkpoint.
    resume = runner.post(f"/api/{slug}/workflow-runs/{run_id}/checkpoint-resume", json={"workflow_step_id": cp_id, "lease_token": lease_token})
    assert resume.status_code == 409

    # Nor can it complete the run PASSED afterward -- lease was cleared,
    # so this fails on the lease check before it could ever touch status.
    complete = runner.post(f"/api/{slug}/workflow-runs/{run_id}/complete", json={"status": "PASSED", "lease_token": lease_token})
    assert complete.status_code == 409

    # A second, later decision attempt (racing tester, retried request,
    # or a bug that tries to "fix" the run) must NOT overwrite the FAIL.
    decide2 = auth_client.post(
        f"/api/{slug}/workflow-runs/{run_id}/checkpoint-decision",
        json={"workflow_step_id": cp_id, "status": "PASS", "actual_result_md": "trying to override"},
    )
    assert decide2.status_code == 409

    decisions = auth_client.get(f"/api/{slug}/workflow-runs/{run_id}/checkpoint-decisions").json()
    assert len(decisions) == 1
    assert decisions[0]["status"] == "FAIL"

    run_final = auth_client.get(f"/api/{slug}/workflow-runs/{run_id}").json()
    assert run_final["status"] == "FAILED"


def test_hyb4_fail_requires_actual_result(auth_client, project_slug):
    slug = project_slug
    ctx = _drive_to_checkpoint(auth_client, slug, suffix="-failreason")
    decide = auth_client.post(
        f"/api/{slug}/workflow-runs/{ctx['run_id']}/checkpoint-decision",
        json={"workflow_step_id": ctx["cp_id"], "status": "FAIL"},
    )
    assert decide.status_code == 400
    assert "actual result" in decide.json()["detail"].lower()


def test_hyb4_blocked_requires_reason_and_stops_run(auth_client, project_slug):
    slug = project_slug
    ctx = _drive_to_checkpoint(auth_client, slug, suffix="-blocked")
    run_id, cp_id = ctx["run_id"], ctx["cp_id"]

    missing_reason = auth_client.post(
        f"/api/{slug}/workflow-runs/{run_id}/checkpoint-decision",
        json={"workflow_step_id": cp_id, "status": "BLOCKED"},
    )
    assert missing_reason.status_code == 400
    assert "reason" in missing_reason.json()["detail"].lower()

    decide = auth_client.post(
        f"/api/{slug}/workflow-runs/{run_id}/checkpoint-decision",
        json={"workflow_step_id": cp_id, "status": "BLOCKED", "reason": "environment is down"},
    )
    assert decide.status_code == 200, decide.text
    assert decide.json()["resume_authorized"] is False

    run_after = auth_client.get(f"/api/{slug}/workflow-runs/{run_id}").json()
    assert run_after["status"] == "BLOCKED"


def test_hyb4_not_applicable_requires_admin_review(auth_client, project_slug):
    slug = project_slug
    ctx = _drive_to_checkpoint(auth_client, slug, suffix="-na")
    run_id, cp_id = ctx["run_id"], ctx["cp_id"]

    decide = auth_client.post(
        f"/api/{slug}/workflow-runs/{run_id}/checkpoint-decision",
        json={"workflow_step_id": cp_id, "status": "NOT_APPLICABLE", "reason": "feature flag disabled in this environment"},
    )
    assert decide.status_code == 200, decide.text
    decision = decide.json()
    assert decision["review_status"] == "UNREVIEWED"

    run_after = auth_client.get(f"/api/{slug}/workflow-runs/{run_id}").json()
    assert run_after["status"] == "NOT_APPLICABLE"

    review = auth_client.post(
        f"/api/{slug}/workflow-runs/{run_id}/checkpoint-decisions/{decision['id']}/review",
        json={"review_status": "ACCEPTED"},
    )
    assert review.status_code == 200, review.text
    assert review.json()["review_status"] == "ACCEPTED"
    assert review.json()["reviewed_by"] == "admin@example.com"


def test_hyb4_decision_conflict_second_racing_decision_rejected(auth_client, project_slug):
    slug = project_slug
    ctx = _drive_to_checkpoint(auth_client, slug, suffix="-conflict")
    run_id, cp_id = ctx["run_id"], ctx["cp_id"]

    first = auth_client.post(
        f"/api/{slug}/workflow-runs/{run_id}/checkpoint-decision",
        json={"workflow_step_id": cp_id, "status": "BLOCKED", "reason": "first reviewer"},
    )
    assert first.status_code == 200

    # A second reviewer racing for the same checkpoint gets an explicit
    # conflict, never a silent overwrite.
    second = auth_client.post(
        f"/api/{slug}/workflow-runs/{run_id}/checkpoint-decision",
        json={"workflow_step_id": cp_id, "status": "PASS", "actual_result_md": "second reviewer, too late"},
    )
    assert second.status_code == 409

    decisions = auth_client.get(f"/api/{slug}/workflow-runs/{run_id}/checkpoint-decisions").json()
    assert len(decisions) == 1
    assert decisions[0]["reason"] == "first reviewer"


def test_hyb4_idempotent_decision_retry_does_not_duplicate(auth_client, project_slug):
    slug = project_slug
    ctx = _drive_to_checkpoint(auth_client, slug, suffix="-idem")
    run_id, cp_id = ctx["run_id"], ctx["cp_id"]

    payload = {"workflow_step_id": cp_id, "status": "BLOCKED", "reason": "flaky network", "idempotency_key": "retry-key-1"}
    first = auth_client.post(f"/api/{slug}/workflow-runs/{run_id}/checkpoint-decision", json=payload)
    assert first.status_code == 200
    second = auth_client.post(f"/api/{slug}/workflow-runs/{run_id}/checkpoint-decision", json=payload)
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"], "a retried decision with the same idempotency_key must not duplicate"

    decisions = auth_client.get(f"/api/{slug}/workflow-runs/{run_id}/checkpoint-decisions").json()
    assert len(decisions) == 1


def test_hyb4_runner_lost_while_paused_is_honest(auth_client, project_slug):
    """Simulates the runner going silent (network loss / process death)
    while WAITING_FOR_HUMAN -- the paused lease must expire and the run
    must be marked RUNNER_LOST, never a fabricated continuation. Prior
    step results, checkpoint context, and (if any) decisions must remain
    intact."""
    slug = project_slug
    import app.models as models_module

    original_paused = models_module.PAUSED_LEASE_DURATION_SECONDS
    wf_id, rev_id, pre_id, cp_id, post_id = _make_workflow_with_checkpoint(auth_client, slug)
    cycle_id, result_id = _make_cycle_result(auth_client, slug, suffix="-lost")
    queued = auth_client.post(f"/api/{slug}/workflow-runs", json={"workflow_revision_id": rev_id, "cycle_test_result_id": result_id}).json()
    run_id = queued["id"]
    token = _issue_runner_token(auth_client, "soon-to-be-lost-runner")
    runner = _fresh_client()
    runner.headers.update({"X-Runner-Token": token})
    lease_token = runner.post(f"/api/{slug}/workflow-runs/claim").json()["lease_token"]
    sr_pre = runner.post(f"/api/{slug}/workflow-runs/{run_id}/step-runs", json={"workflow_step_id": pre_id, "lease_token": lease_token}).json()
    runner.put(f"/api/{slug}/workflow-runs/{run_id}/step-runs/{sr_pre['id']}", json={"status": "PASSED", "lease_token": lease_token})

    try:
        # Shrink the paused-lease window to ~0 BEFORE the checkpoint pause
        # is recorded, so the lease it's granted is already effectively
        # expired.
        models_module.PAUSED_LEASE_DURATION_SECONDS = 0
        runner.post(
            f"/api/{slug}/workflow-runs/{run_id}/events",
            json={"event_type": "CHECKPOINT_WAITING", "actor_type": "RUNNER", "lease_token": lease_token},
        )
        time.sleep(0.05)

        detail = auth_client.get(f"/api/{slug}/workflow-runs/{run_id}").json()
        assert detail["status"] == "RUNNER_LOST"
        assert any(e["event_type"] == "RUNNER_LOST" for e in detail["events"])
        # The prior automated step result is preserved, not discarded.
        assert len(detail["step_runs"]) == 1
        assert detail["step_runs"][0]["status"] == "PASSED"

        # A human decision arriving after the runner is already lost must
        # be rejected, not silently accepted against a dead session.
        decide = auth_client.post(
            f"/api/{slug}/workflow-runs/{run_id}/checkpoint-decision",
            json={"workflow_step_id": cp_id, "status": "BLOCKED", "reason": "too late, runner already lost"},
        )
        assert decide.status_code == 409
    finally:
        models_module.PAUSED_LEASE_DURATION_SECONDS = original_paused


def test_hyb4_locked_cycle_blocks_checkpoint_decisions(auth_client, project_slug):
    slug = project_slug
    ctx = _drive_to_checkpoint(auth_client, slug, suffix="-locked")
    lock = auth_client.post(f"/api/{slug}/cycles/{ctx['cycle_id']}/lock")
    assert lock.status_code == 200, lock.text

    decide = auth_client.post(
        f"/api/{slug}/workflow-runs/{ctx['run_id']}/checkpoint-decision",
        json={"workflow_step_id": ctx["cp_id"], "status": "BLOCKED", "reason": "cycle is locked"},
    )
    assert decide.status_code == 400
    assert "LOCKED" in decide.json()["detail"]

    reopen = auth_client.post(f"/api/{slug}/cycles/{ctx['cycle_id']}/reopen", json={"reason": "test cleanup"})
    assert reopen.status_code == 200


def test_hyb4_defect_created_from_checkpoint_carries_full_provenance(auth_client, project_slug):
    slug = project_slug
    ctx = _drive_to_checkpoint(auth_client, slug, suffix="-defect")
    decide = auth_client.post(
        f"/api/{slug}/workflow-runs/{ctx['run_id']}/checkpoint-decision",
        json={"workflow_step_id": ctx["cp_id"], "status": "FAIL", "actual_result_md": "layout broken"},
    ).json()

    defect = auth_client.post(
        f"/api/{slug}/defects",
        json={
            "title": "Layout broken at checkpoint",
            "cycle_id": ctx["cycle_id"],
            "cycle_test_result_id": ctx["result_id"],
            "severity": "P1",
            "workflow_run_id": ctx["run_id"],
            "checkpoint_decision_id": decide["id"],
        },
    )
    assert defect.status_code == 200, defect.text
    body = defect.json()
    assert body["workflow_run_id"] == ctx["run_id"]
    assert body["checkpoint_decision_id"] == decide["id"]


def test_hyb4_resume_rejects_wrong_lease_token(auth_client, project_slug):
    slug = project_slug
    ctx = _drive_to_checkpoint(auth_client, slug, suffix="-wronglease")
    run_id, cp_id = ctx["run_id"], ctx["cp_id"]
    auth_client.post(
        f"/api/{slug}/workflow-runs/{run_id}/checkpoint-decision",
        json={"workflow_step_id": cp_id, "status": "PASS", "actual_result_md": "ok", "evidence_ids": [ctx["screenshot_id"]]},
    )
    resume = ctx["runner"].post(
        f"/api/{slug}/workflow-runs/{run_id}/checkpoint-resume",
        json={"workflow_step_id": cp_id, "lease_token": "not-the-real-lease-token"},
    )
    assert resume.status_code == 409
