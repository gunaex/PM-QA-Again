# Session Handoff — Hybrid MVP delivery, paused after HYB-2

Written 2026-08-02. This is a **deliberate clean stop between phases**,
not a crash or a discovered blocker — see "Why stopped here" below.
Supersedes the previous version of this file (written after HYB-1).

## Current state

- **Branch**: `feature/hybrid-mvp`
- **HYB-1 completion commit**: `8d64495`
- **HYB-2 completion commit**: recorded at the end of this session (see
  the commit this file was pushed alongside — check `git log --oneline
  -1 feature/hybrid-mvp` for the exact hash after push).
- **`main`** is at `bb2f539` — unaffected; all hybrid work lives only on
  `feature/hybrid-mvp`.
- **`track-a-baseline` tag**: `bb2f539`.
- Working tree: clean except `docs/Autonomous hybird prompt.md` (the
  user's own file, intentionally left untouched/unstaged throughout).

## HYB-1 — complete (unchanged from the previous handoff, not re-verified this session, not re-touched)

See the previous handoff's content, preserved in git history
(`8d64495`). Do not redo, rewrite, or re-verify it.

## HYB-2 — complete and verified this session

**Files**:
- `backend/app/models.py` — `RunnerToken` extended (additive) with
  `runner_name`/`runner_version`/`os_metadata`/`browser_version`/
  `capabilities_json`/`last_heartbeat_at`; `EvidenceItem` extended
  (additive) with nullable `workflow_run_id`/`workflow_step_run_id`;
  new `WorkflowRun`, `WorkflowStepRun`, `RunnerExecutionEvent` tables.
- `backend/app/schemas.py` — matching schemas
  (`WorkflowRunOut`/`WorkflowRunDetailOut`/`WorkflowStepRunOut`/
  `RunnerExecutionEventOut`/`WorkflowRunClaimOut`/etc.,
  `RunnerRegistrationOut`).
- `backend/app/database.py` — `MASTER_COLUMN_PATCHES["runner_tokens"]`,
  `PROJECT_COLUMN_PATCHES["evidence_items"]`, new `PROJECT_INDEXES`
  entries for the three new tables.
- `backend/app/auth.py` — `get_current_runner` now touches
  `last_heartbeat_at` on every authenticated runner call;
  `revoke_runner_token` added.
- `backend/app/routers/runner_tokens.py` — rewritten: list (admin,
  computed ONLINE/STALE/OFFLINE/REVOKED status), revoke (admin).
  Create endpoint unchanged.
- `backend/app/routers/workflow_runs.py` — new. The full job-claim
  protocol: queue, list, detail, claim, heartbeat, events (idempotent),
  step-runs (start/finish), evidence upload (reuses real
  `EvidenceStorage`), complete, cancel. `_require_user_or_runner` added
  for the one endpoint (`GET /{run_id}`) both the runner and the human
  UI need to read.
- `backend/app/main.py` — router wired in.
- `backend/tests/test_workflow_runs.py` — new, 7 tests, all passing.
- `runner/src/api/executionClient.ts` — new job-protocol client.
- `runner/src/execution/locators.ts` — structured locator resolution +
  sensitive-value `${VAR}` resolution + failure categorization.
- `runner/src/execution/executor.ts` — real step execution against a
  persistent Playwright page, claim/execute loop, checkpoint pause.
- `runner/src/executeMain.ts` — new entry point (`npm run execute`).
  `runner/src/main.ts` (HYB-0 `npm run spike`) is **untouched**.
- `runner/package.json` — added the `execute` script.
- `frontend/src/pages/RunnerList.jsx` — new, admin-only runner
  management (register/list/revoke, live status).
- `frontend/src/pages/WorkflowDetail.jsx` — added a "Runs" panel (queue,
  live-polling list, expandable step-run/event detail, cancel).
- `frontend/src/pages/ProjectList.jsx`, `App.jsx` — `/runners` route +
  nav link wired in.
- `docs/ROADMAP.md` — updated with full HYB-2 detail.

**Design/scope decisions made this phase** (documented in code
comments, not silent):
- One `RunnerToken` row = one runner identity+credential (no separate
  `runners` table) — matches HYB-0's original decision, just extended
  with the fields HYB-2 needs.
- Lease lives directly on `WorkflowRun` (`lease_token`/
  `lease_expires_at`), not a separate `RunnerLease` table — a run has
  at most one active claim at a time in this MVP (no multi-runner
  fan-out per job), so a 1:1 table would be overhead without a use.
- Lease expiry is a **lazy sweep** (`_expire_stale_leases`, called at
  the top of every relevant endpoint), not a background cron/scheduler
  — no new dependency, and it self-heals on the very next API call
  against the project, which is sufficient for this MVP's scale.
- `MANUAL_CHECKPOINT` steps cause the runner to pause and exit cleanly
  (posts `CHECKPOINT_WAITING`, does not advance further, does not call
  `/complete`) rather than building fake resume semantics — full
  checkpoint pause/resume with a human decision UI is explicitly HYB-4's
  objective, not HYB-2's.
- Evidence upload requires the run to carry a `cycle_test_result_id`
  (checked, 400 if absent) — preserves `EvidenceItem`'s existing NOT
  NULL `cycle_id`/`cycle_test_result_id` columns completely unchanged
  rather than weakening them for standalone runs.

**Bugs found and fixed via the real end-to-end run** (not code review):
1. `GET /workflow-runs/{id}` required a user session; the runner's own
   cancel-check poll only holds a token → 401. Fixed with
   `_require_user_or_runner` (same dual-credential pattern as HYB-0's
   `hybrid.py::get_run`).
2. `ASSERT_TEXT`/`ASSERT_URL` checked the page exactly once immediately
   after a `CLICK`, before the SPA finished navigating → false failure.
   Fixed with `pollUntil()`, retrying within the step's timeout.

**Verification**:
- Backend: `pytest` — **52/52 passing** (45 carried from HYB-1 + 7 new),
  fresh `.venv`.
- Frontend: `npm run build` — clean, fresh `node_modules`.
- Runner: `tsc --noEmit` — clean, fresh `node_modules`.
- **Real end-to-end execution, not mocked**: registered a real runner
  token, queued a real run against a published workflow revision (a
  real login flow: NAVIGATE → FILL email → FILL a sensitive
  `${RUNNER_LOGIN_PASSWORD}` placeholder → CLICK Sign in → ASSERT_TEXT
  "Projects" → SCREENSHOT) linked to a real Track A cycle result, ran
  the real Node.js/TypeScript process (`npm run execute`) which
  launched real headed Chromium and executed every step for real
  against the real running frontend+backend. First attempt genuinely
  failed at the ASSERT_TEXT race (bug 2 above) and was caught by a
  real lease-expiry timeout that correctly marked the crashed attempt
  `RUNNER_LOST` (proving that mechanism works too) — the *second*
  attempt, after the fix, PASSED end to end. Confirmed via the API
  (structured step-run rows, a real 21,677-byte PNG evidence item
  visible through Track A's own evidence endpoint,
  `evidence_source=RUNNER`) and via a real headed-browser Playwright
  pass through the actual `RunnerList`/`WorkflowDetail` UI.

## Current in-progress phase

**None.** HYB-3 has not been started.

## Not yet done

- HYB-3: browser workflow recorder (semantic locator capture from real
  DOM interactions, sensitive-input detection/redaction, noise
  reduction, recorder UI, draft-workflow generation, replay-by-HYB-2
  verification).
- HYB-4: manual checkpoints and hybrid evidence — this is where
  `MANUAL_CHECKPOINT`'s pause (built in HYB-2, not resumable yet) gets
  a real human-decision resume flow, and where the
  `HYB-1-GAP-ANALYSIS-REFRESH.md` evidence-reuse decision gets its
  `checkpoint_decision_id` link once a checkpoint-decision table exists.
- HYB-5: timing, reports, `HYBRID_RUNNER_THREAT_MODEL.md`, recovery
  docs, user guides.

## Why stopped here

Same reasoning as the HYB-1→HYB-2 stop: HYB-3 (a real browser action
recorder — capturing live DOM interactions into semantic locators,
detecting and redacting sensitive fields, noise-reduction heuristics,
a full recorder UI) is another substantial, genuinely new subsystem
that deserves its own full build-and-verify pass rather than being
compressed into the same session as HYB-2's real-runner debugging.
This is a deliberate stop at a clean phase boundary per the user's own
documented fallback instruction, applied proactively.

## Exact next implementation step

1. Read this file in full — HYB-2's job-claim protocol, runner client,
   and executor are what HYB-3's recorder must produce output
   compatible with (a `WorkflowRevision` + ordered `WorkflowStep` rows
   with structured locators, ready to `/claim` and execute exactly like
   the hand-written test workflow this session executed for real).
2. Read `docs/Autonomous hybird prompt.md`'s HYB-3 section in full —
   the recorder-safety rules (browser-session-only recording, no
   OS-level keylogging, semantic locators not raw coordinates, never
   persist real passwords/OTPs/tokens, noise reduction without silent
   behavior changes) are non-negotiable constraints, not suggestions.
3. Design where recording happens: almost certainly the QA Runner
   process (`runner/`) attaches Playwright's own action-recording
   capability (or a custom `page.exposeFunction`/CDP-based listener) to
   a browser session it launches itself — never a browser extension or
   global OS hook. Decide and document this before writing code.
4. Design the sensitive-field detector (input `type="password"`,
   `autocomplete` attribute, name/label pattern matching) and confirm
   it reuses the exact `${VAR_NAME}` placeholder convention
   `workflow_steps.input_value`/`is_sensitive` already established in
   HYB-1/HYB-2 — do not invent a second convention.
5. Recorder output must be a DRAFT `WorkflowRevision` (via HYB-1's
   existing `POST /workflows/{id}/revisions` + step-creation endpoints)
   — never auto-published. A human reviews and publishes manually,
   exactly like every other DRAFT→PUBLISHED flow in this app.
6. Full gate: backend pytest, frontend build, runner
   build/typecheck, then a real headed-browser recording session
   (record a real flow with a password field, confirm the raw password
   never appears in the resulting workflow JSON or any log line, confirm
   the recorded draft can be published and then actually executed by
   HYB-2's real runner against the same target app).
7. Update `docs/ROADMAP.md`, write a fresh
   `docs/hybrid/SESSION_HANDOFF.md` (or append if HYB-3 also stops
   between phases), commit, push to `feature/hybrid-mvp`, record the
   hash, proceed to HYB-4 under the same discipline.

## Exact commands to resume

```bash
cd d:/git/PM-QA-Again
git checkout feature/hybrid-mvp
git pull origin feature/hybrid-mvp
git log --oneline -5   # confirm HYB-2's commit is at or near HEAD

# Backend
cd backend
python -m venv .venv
./.venv/Scripts/pip install -r requirements-dev.txt
./.venv/Scripts/python -m pytest -q   # expect 52 passed

# Frontend
cd ../frontend
npm install
npm run build   # expect clean

# Runner
cd ../runner
npm install
npm run typecheck   # expect clean
npx playwright install chromium   # if not already cached
```

To manually re-verify HYB-2's real execution (optional, already proven
this session): start backend+frontend, create a project/workflow/cycle
via curl (see this session's transcript or re-derive from
`backend/app/routers/workflow_runs.py`'s docstring), issue a runner
token via `POST /api/runner-tokens`, write `runner/.env` (gitignored —
`BACKEND_BASE_URL`, `PROJECT_SLUG`, `RUNNER_TOKEN`, `TARGET_BASE_URL`,
plus whatever `${VAR}` names your test workflow's sensitive steps
reference), queue a run, `npm run execute`.

## Continuation prompt (copy-paste into a fresh session)

```
Continue the QA-Again Hybrid MVP delivery. Read
docs/hybrid/SESSION_HANDOFF.md in full first -- it has the exact
current state, what HYB-1 and HYB-2 completed and verified (including
two real bugs found via an actual end-to-end runner execution, not
code review), and the precise next step. Branch is feature/hybrid-mvp.
Do not start over or re-verify HYB-1/HYB-2 (already done: 52/52 backend
tests, frontend build clean, runner typecheck clean, a real Node.js
runner process really executed a real login workflow against real
headed Chromium end to end, with real screenshot evidence recorded
through the actual EvidenceStorage system). Begin HYB-3 (browser
workflow recorder) per docs/Autonomous hybird prompt.md's HYB-3
section, following the same discipline as HYB-1/HYB-2: real
FastAPI/SQLite/Node.js/TypeScript/Playwright behavior only, no mocked
output as completion evidence, full backend/frontend/runner gates plus
real-browser verification (including a live recording session with a
password field, confirming the raw password never appears anywhere in
the output) before considering the phase done. Commit and push HYB-3
separately. Release Closure's three human-operated checks remain
unresolved and the project remains NOT PRODUCTION READY regardless of
hybrid progress -- do not claim otherwise.
```
