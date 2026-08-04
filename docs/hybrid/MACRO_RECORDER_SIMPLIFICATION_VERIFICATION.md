# Macro-Recorder-Style Simplification (Phases A–E) — Verification

Verifies the full 5-phase redesign of the Hybrid recorder/runner UX,
triggered by a non-technical tester reporting the flow as "very hard
to test with step report" and asking for something closer to a game
macro-recorder (record, click, type, see result, wait, loop, save).
Delivered as five separately-committed, separately-verified phases per
the approved plan.

**Non-negotiable constraint, held throughout every phase**: Publish
stays ADMIN-only, unconditional, no bypass — confirmed explicitly with
the tester before starting, and never touched by any phase (Phase E's
preview run in particular is architected specifically to deliver
"click test, see result" for a TESTER without ever needing an admin,
while a *real*, audited run still always requires a PUBLISHED revision
an admin approved).

## Environment

Each phase was verified against a freshly-started isolated backend
(`uvicorn`, fresh SQLite `DATA_DIR`) and frontend (`vite`), both on
matching `127.0.0.1` hostnames (mixing `localhost`/`127.0.0.1` breaks
`SameSite=Lax` cookies — a hard rule in this project). Browsers were
launched via the tracked-lifecycle helper
(`runner/scripts/lib/browserLifecycle.mjs`); every pass confirmed zero
leaked `qa-again-playwright-*` Chrome processes afterward via
`Win32_Process`. Scratch verification scripts and data directories were
deleted after each phase — none are committed.

## Phase A — Always-on runner

**Problem root-caused**: nothing ever executed a queued run
automatically (`npm run execute` claimed one run and exited); a tester
who queued a run and saw the ever-present red "Cancel" link on a
non-terminal run reasonably read that as broken.

**Changes**: `runner/src/executeMain.ts --watch` loops
`claimAndExecuteOnce` forever instead of exiting; `runner/start-runner.ps1`
/ `.bat` double-clickable launchers; `GET /runner-tokens/status`
(any-authenticated-user-readable, returns only an aggregate
`any_online` boolean — never labels/ids) backs a "Runner: Online/Offline"
badge + guidance banner on `WorkflowDetail.jsx`'s Runs section.

**Verified**: isolated backend/frontend, started the watcher *before*
any run existed, queued two sequential runs — both claimed and PASSED
automatically within ~1s each. `any_online: true` confirmed via curl.
Backend test `test_runner_fleet_status_is_readable_by_tester_not_just_admin`
added. Zero leaked processes.

## Phase B — Human-friendly step & result display

**Problem**: raw `step_type`/locator strings and a scrolling event log
were the only run-result view; no big "did it work" signal.

**Changes**: `frontend/src/utils/describeStep.js` (`describeStep()` →
`{icon, text}`, e.g. `{"🖱️", "Click the Login button"}`), applied in
`RecordingPanel.jsx`, `WorkflowDetail.jsx`'s step/step-run lists, and
`CheckpointPanel.jsx`; a top-level ✅/❌/⏳ `RunResultBanner`; raw event
log moved behind a collapsed-by-default "Show Developer Data" toggle
(matching the Reports page's existing pattern). Backend:
`WorkflowStepRunOut` extended with the step's own descriptive fields so
step-*run* results render specifically ("Type into \"Email\"") not just
step-*authoring* rows.

**Verified**: two real-browser passes (first found the generic-text gap
in step-run rendering, second confirmed the backend fix fixed it) —
plain-language text confirmed for every step type used, both in the
Steps-authoring list and a FAILED run's step-run list. Backend test
`test_step_run_detail_carries_step_fields_for_plain_language_display`
added. Zero leaked processes.

## Phase C — Sensitive-field placeholder auto-suggestion

**Problem**: a password/OTP/token field the recorder captured left the
"Variable name" box empty — the tester had to learn the `${VAR_NAME}`
syntax from a blank box before Save was even possible (the literal
"FILL requires input_value" error the tester hit).

**Changes**: once a session STOPS, any sensitive step still missing a
value gets an auto-suggested name (password → `${LOGIN_PASSWORD}`,
otp → `${LOGIN_OTP}`, etc., falling back to `${SECRET_N}`), saved
immediately — the tester can accept it as-is or edit/clear it.

**Two real bugs found and fixed during verification** (not part of the
original plan):
1. `extension/background.js`'s `fetch()` didn't set `credentials:
   "omit"`. A tester logged into the QA-Again web app in the *same*
   Chrome profile as the extension gets that session cookie
   auto-attached to the extension's cross-origin requests
   (`host_permissions` grants normal cookie access), tripping the
   backend's CSRF-origin guard and 403ing every extension call even
   though the extension authenticates purely via its own
   `extension_token`.
2. `RecordingPanel.jsx` never reset the pairing-code (`extensionToken`)
   state when starting a new session or discarding one — restarting a
   recording after a discard displayed a *stale* pairing code tied to
   the old, now-invalid session.

**Verified**: real headed-Chrome pass loading the actual extension,
recording a genuine password FILL on a real target page (confirmed
`is_sensitive=true`, `input_value=null` *before* any suggestion logic
ran — the raw value is never sent to the backend), stopped via the
real QA-Again UI, confirmed the "Variable name" box auto-filled
`${LOGIN_PASSWORD}` with no manual typing, confirmed it's genuinely
persisted server-side (not a stale client default), and confirmed Save
as Draft Revision then succeeded. Zero leaked processes.

## Phase D — WAIT step type and per-step REPEAT

**Problem**: no time-based pause or "click this N times" primitive
existed at all.

**Changes**: new `WAIT` step type (`input_value` = milliseconds,
executor does a plain `setTimeout` pause); optional `repeat_count` on
any repeatable step type (CLICK/FILL/SELECT/CHECK/UNCHECK/PRESS_KEY/
SCREENSHOT) — the runner re-executes that single step in place N times,
each attempt getting its own step-run row (`attempt_number` 1..N,
reusing an already-existing-but-previously-unused column). A "Repeat
×N" input next to Queue Run queues the same published revision N times
(reuses the existing multi-queue mechanism, nothing new server-side).
Additive `workflow_steps.repeat_count` column.

**Verified**: built NAVIGATE → CLICK(repeat_count=3) → WAIT(1500ms),
published, queued, executed through the real claim/execute/complete
protocol against a real headed browser — confirmed the run's
wall-clock duration included the full WAIT pause, and the repeated
CLICK produced exactly 3 separate PASSED step-run rows
(`attempt_number` 1,2,3). Separately confirmed in a real browser that
the WAIT-ms input and Repeat-×N input render at the right times in the
Add Step form, and that the Queue Run Repeat-×N control only appears
for a PUBLISHED revision. Zero leaked processes.

## Phase E — "Test It Now" preview run

**Problem**: the actual "record → click test → see it worked" loop for
a TESTER required an admin to publish first — even to sanity-check
their own recording. Confirmed with the tester: Publish must stay
ADMIN-only unconditionally, so this had to be solved *without* any
publish bypass.

**Changes**: `POST /workflow-runs/preview` — targets any revision
directly (including DRAFT), skips the PUBLISHED-only gate, but runs
through the *exact same* claim/execute/complete protocol a real run
uses. A dedicated `WorkflowPreviewRunCreate` schema has no
`cycle_test_result_id` field at all (not optional-and-ignored,
structurally absent). New `WorkflowRun.is_preview` column, excluded
from every Track B reporting aggregate (`hybrid_metrics.py`,
`hybrid_timing.py`) — a preview is a private sanity check, never part
of the audited record — while still visible (clearly badged "Preview")
in the plain run list. `RecordingPanel.jsx` shows a "Test It Now"
button after Save as Draft Revision succeeds, polling the shared
`RunResultBanner` component (extracted from `WorkflowDetail.jsx` in
this phase) until terminal.

**Verified**: recorded a real workflow via the Chrome extension, saved
as DRAFT, clicked Test It Now, confirmed the revision stayed DRAFT
before *and after* (never silently published), let the real runner
executor claim and PASS it, confirmed `RecordingPanel` showed the
PASSED banner inline, and confirmed the hybrid-reports dashboard's
`run_status_counts` did **not** move even though the preview run just
completed PASSED. Backend test
`test_preview_run_targets_a_draft_revision_and_is_excluded_from_reporting`
added (uses a before/after dashboard-count delta rather than exact
counts, since the test-suite's project fixture is session-shared).
Zero leaked processes.

## Test/build summary (final state, all phases)

- `cd backend && pytest` — **125 passed**.
- `cd frontend && npm run build && npm run lint` — clean (only
  pre-existing, unrelated warnings in `RecordingPanel.jsx`'s unused
  `ACTIVE_STATUSES` and `CycleExecution.jsx`).
- `cd runner && npm run typecheck` — clean.

## What this does not close

- Not production-ready; no merge to `main` performed or implied.
- Phase A's runner-online indicator reflects *any* runner online
  project-wide, not specifically one able to reach a given target
  environment — a documented simplification, not a bug.
- Phase D's `retry_frequency` metric (`hybrid_metrics.py`) does not yet
  distinguish a deliberate `repeat_count` re-execution from an actual
  failure-triggered retry — both produce `attempt_number > 1` rows and
  are currently counted the same way. Not fixed in this pass (existing
  metric definition, out of scope for this redesign).
- The pre-existing "a `WorkflowRun` with no `cycle_test_result_id`
  cannot upload evidence" gap (documented in `workflow_runs.py`,
  predates this work) applies equally to preview runs — a preview
  workflow with a SCREENSHOT or MANUAL_CHECKPOINT step will fail at
  that step. Verification scripts avoided this by construction; not a
  regression introduced by Phase E.
