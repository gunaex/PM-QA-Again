# HYB-5 Real Headed-Browser Verification (50+ Steps)

Executed 2026-08-02, superseding
[HYB5_VERIFICATION_SCOPE.md](HYB5_VERIFICATION_SCOPE.md)'s prior
"not done this session" item — this is the real, previously-missing
headed-Chromium run. **Not an HTTP runner-token simulation**: the real
Node.js/TypeScript runner (`npm run execute`, `runner/src/execution/
executor.ts`), a real headed Chromium (`chromium.launch({ headless:
false })`), driven against the **real running QA-Again frontend**
(Vite dev server) and **real running backend** (uvicorn) — not a
synthetic target page.

## Setup

- Real backend: `uvicorn` on `127.0.0.1:8000`, fresh `data/` directory.
- Real frontend: `npm run dev` (Vite) on `localhost:5173`.
- `backend/scripts/hyb5_real_browser_setup.py` (committed script; talks
  only to the real HTTP API) built a real project, a real 72-step
  workflow, a real linked Track A cycle result, and issued a real
  runner token.
- `runner/.env` (gitignored, deleted immediately after this
  verification) pointed the real runner at this real backend/frontend.

## Workflow structure (72 steps, one published revision per run)

- Real login: `NAVIGATE /login` → `FILL` email → `FILL` password
  (**sensitive**, `is_sensitive: true`, `input_value: "${TARGET_PASSWORD}"`,
  resolved at runtime from the runner's own `process.env.TARGET_PASSWORD`
  — never stored as a literal value anywhere in the workflow definition)
  → `CLICK` "Sign in" → `ASSERT_TEXT`/`SCREENSHOT`.
- Real `CHECK`/`ASSERT_VISIBLE`/`UNCHECK` of the Projects page's "Show
  archived" checkbox.
- Real `NAVIGATE` into the created project's dashboard.
- Three real laps around every nav tab (Test Suites, Test Cycles,
  Reports, Workflows, Hybrid Reports, Dashboard), each hop a real
  `CLICK` + `ASSERT_URL` + `SCREENSHOT` against the real rendered React
  app.
- A real `SELECT` on the Hybrid Reports page's workflow-trend dropdown
  (selecting the demo workflow by its exact name).
- A real `MANUAL_CHECKPOINT` mid-way (step 35/107).
- A deliberately failing final `ASSERT_TEXT` step in revision v1 (a
  genuine, unmet assertion — not a crash, not a mock).

**Real bug found and fixed during this verification**: the first draft
of the nav-tab `CLICK` steps used `ROLE:link:<name>` locators; Playwright's
`getByRole(..., { name })` does *substring*, case-insensitive matching
by default, so `name: "Reports"` genuinely matched **both** "Reports"
and "Hybrid Reports" nav links — a real `LOCATOR_AMBIGUOUS` failure on
the actual first run attempt. Fixed by switching those steps to
`CSS: 'nav :text-is("...")'` (Playwright's exact-text CSS pseudo-class).
This is exactly the kind of genuine locator issue the hybrid runner's
failure-categorization exists to catch and report honestly, and it was
caught for real, not hypothesized.

## Run 1 — against v1 (includes the deliberate failing tail)

Real headed Chromium, real login, real navigation through 34 real
steps, then:

```
[runner] run 1: reached MANUAL_CHECKPOINT at step 35 -- pausing, keeping the browser session alive
```

Confirmed server-side: `GET /workflow-runs/1` → `status: WAITING_FOR_HUMAN`,
real `checkpoint_waiting_since` timestamp. A real human decision was
submitted via the same endpoint the UI's `CheckpointPanel.jsx` calls:

```
POST /workflow-runs/1/checkpoint-decision
{"workflow_step_id": 35, "status": "PASS",
 "actual_result_md": "Real human review: Hybrid Reports page rendered
 correctly with the workflow selected."}
```

The **same, still-running** runner process observed `RESUMING` on its
next poll, called `/checkpoint-resume`, and continued in the **same**
Chromium browser/page object — steps 36–71 (two more full nav laps)
all `PASSED`. Step 72 (the deliberate failing `ASSERT_TEXT`) then
genuinely failed:

```
[runner] run 1: step 72 FAILED (ASSERTION_FAILED)
[runner] run 1: complete (FAILED)
[runner] exiting -- finalStatus=FAILED pausedAtCheckpoint=true resumedFromCheckpoint=true
```

### Run 1 — real recorded results

| Metric | Value |
|---|---|
| Step count | 72 |
| Result | 71 PASSED, 1 FAILED (step 72, `ASSERTION_FAILED`) |
| Total run duration | 68.163 s |
| Queue/claim delay | 15.05 s |
| Browser startup | 0.802 s |
| Application step time (sum) | 47.291 s |
| Manual waiting time (checkpoint) | 21.38 s |
| Checkpoint entered → decided | 21.38 s |
| Resume delay (decision → runner resumed) | 0.045 s |
| Evidence items uploaded | 14 (real PNG screenshots) |
| Provenance | `HUMAN`: `RUN_QUEUED`, `CHECKPOINT_DECIDED`. `RUNNER`: `RUN_CLAIMED`, `STEP_STARTED`, `STEP_COMPLETED`, `CHECKPOINT_WAITING`, `RUN_RESUMED`, `HEARTBEAT`, `RUN_COMPLETED` |

Source: `GET /hybrid-reports/timing/runs/1` (this app's own real HYB-5
timing endpoint, reading real captured timestamps — not hand-computed).

## Retry: Run 2 — deliberate rerun against a corrected revision

Following the recovery runbook's documented "safe retry / deliberate
rerun" pattern (never mutate a terminal run in place): the workflow's
v1 revision was cloned into `v2-corrected` (real `POST .../clone`), the
failing tail step was deleted (real `DELETE .../steps/{id}`), a
corrected assertion (`expected_value: "Dashboard"`, real text on the
page) was added, and v2 was published (real `POST .../publish`, which
correctly superseded v1 per this app's immutable-revision discipline).
A new run (Run 2) was queued against v2 and executed by the real
runner from scratch.

```
[runner] run 2: reached MANUAL_CHECKPOINT at step 35 -- pausing, keeping the browser session alive
```
→ real human PASS decision submitted (`workflow_step_id: 107`, the new
revision's own step id — cloning creates new step rows, confirmed via
`GET /workflow-runs/2`'s real `step_runs`) →

```
[runner] run 2: step 72 PASSED
[runner] run 2: complete (PASSED)
[runner] exiting -- finalStatus=PASSED pausedAtCheckpoint=true resumedFromCheckpoint=true
```

### Run 2 — real recorded results

| Metric | Value |
|---|---|
| Step count | 72 |
| Result | **72 PASSED, 0 FAILED** |
| Total run duration | 89.649 s |
| Queue/claim delay | 7.154 s |
| Browser startup | 0.699 s |
| Application step time (sum) | 76.334 s |
| Manual waiting time (checkpoint) | 66.957 s (a real, longer human deliberation this time) |
| Resume delay | 0.252 s |
| Evidence items uploaded | 8 |
| Provenance | Same disjoint `HUMAN`/`RUNNER` split as Run 1 |

## What this proves, concretely

- **Same-session resume is real**, not simulated: the runner process
  that paused at the checkpoint in each run is the exact same OS
  process that resumed and executed the remaining 37 steps — confirmed
  by the unbroken `pausedAtCheckpoint=true resumedFromCheckpoint=true`
  result and the continuous step-sequence log with no re-claim/
  re-launch in between.
- **Sensitive-variable injection is real**: the login password field
  was filled from `${TARGET_PASSWORD}`, resolved only inside the
  runner's own environment — the literal password value never appears
  in the workflow definition, this document, or any committed file.
- **A genuine failure occurred and was categorized correctly** (twice,
  in fact: the unplanned `LOCATOR_AMBIGUOUS` bug found and fixed during
  setup, and the deliberate `ASSERTION_FAILED` in Run 1).
- **A genuine retry-after-fix succeeded**, exercising the real
  clone → fix → republish → rerun path end to end.
- **Timing records are real**, produced by this session's own HYB-5
  `hybrid_timing.py` module reading real captured timestamps from a
  real execution, not estimated.
- **Provenance stays genuinely disjoint** between `HUMAN` and `RUNNER`
  actor types across both runs.

## Cleanup

`runner/.env` (held the real, session-scoped runner token — no
production credential) was deleted immediately after this verification.
The demo project's data lived under `backend/data/` (gitignored, not
committed) and was cleared before the subsequent clean-environment
rehearsal (see [RELEASE_REHEARSAL.md](../RELEASE_REHEARSAL.md)).
