# Session Handoff — Hybrid MVP delivery, paused after HYB-3

Written 2026-08-02. This is a **deliberate clean stop between phases**,
not a crash or a discovered blocker — see "Why stopped here" below.
Supersedes the previous version of this file (written after HYB-2).

## Current state

- **Branch**: `feature/hybrid-mvp`
- **HYB-1 commit**: `8d64495`
- **HYB-2 commit**: `0071a23`
- **HYB-3 commit**: recorded at the end of this session — check
  `git log --oneline -1 feature/hybrid-mvp` for the exact hash after
  push (committed and pushed immediately after this file).
- **`main`** is at `bb2f539` — unaffected; all hybrid work lives only on
  `feature/hybrid-mvp`.
- **`track-a-baseline` tag**: `bb2f539`.
- Working tree: clean except `docs/Autonomous hybird prompt.md` (the
  user's own file, intentionally left untouched/unstaged throughout).

## HYB-1 and HYB-2 — complete, unchanged, not re-verified this session

See prior handoff content preserved in git history (`8d64495`,
`0071a23`) and `docs/ROADMAP.md`. Do not redo, rewrite, or re-verify.

## HYB-3 — complete and verified this session

**Files**:
- `backend/app/models.py` — `RecordingSession`, `RecordedStep` (project-
  scoped, same claim/lease shape as `WorkflowRun`).
- `backend/app/schemas.py` — matching schemas.
- `backend/app/database.py` — new `PROJECT_INDEXES` entries.
- `backend/app/routers/recording_sessions.py` — new. Full protocol:
  create/list/detail, pause/resume/stop/discard, insert-checkpoint,
  edit/delete/reorder recorded steps, test-locator request/result,
  save-as-draft (reuses `workflows.py::_validate_step_fields`), and the
  runner-facing claim/heartbeat/append-step/pending-locator-tests
  endpoints. `_require_user_or_runner` (same dual-credential pattern as
  HYB-2) on the one endpoint both sides read.
- `backend/app/main.py` — router wired in.
- `backend/tests/test_recording_sessions.py` — new, 5 tests, all
  passing.
- `runner/src/recorder/domRecorder.ts` — new. The in-page recording
  script (injected via `page.addInitScript`).
- `runner/src/recorder/recordSession.ts` — new. Node-side orchestration:
  claim, launch, inject, expose bridge, poll loop (heartbeat/pause-
  resume/pending-locator-tests), close on STOPPED/DISCARDED.
- `runner/src/api/recordingClient.ts` — new. HTTP client for the
  recording-session protocol.
- `runner/src/recordMain.ts` — new entry point (`npm run record`).
  `main.ts` (`npm run spike`) and `executeMain.ts` (`npm run execute`)
  are **untouched**.
- `runner/package.json` — added the `record` script.
- `frontend/src/components/RecordingPanel.jsx` — new. The tester's
  remote control (Start/Pause/Resume/Stop/Discard, live step list,
  insert-checkpoint, per-step locator testing, review/edit/reorder,
  save-as-draft).
- `frontend/src/pages/WorkflowDetail.jsx`, `api/client.js` — wired in.
- `docs/ROADMAP.md` — updated with full HYB-3 detail.

**Architecture decision**: recording happens inside a browser the QA
Runner process itself launches (a genuinely separate browser window
from whatever the tester's own everyday browser is doing) — the
tester's frontend is the *remote control*, not the recorded surface
itself. This is what the hybrid prompt's "operate only inside the
controlled Playwright browser session" requirement means in practice.
`RecordingSession`/`RecordedStep` are a separate, editable, discardable
draft buffer — "Save as Draft" is a distinct, explicit action that
reuses HYB-1's own revision/step-creation code one field at a time, so
a saved recording is indistinguishable from a hand-built draft, not a
parallel code path with its own bugs to keep in sync.

**Four real bugs found and fixed via the actual real recording run,
not code review** (see `docs/ROADMAP.md`'s HYB-3 entry for full detail
on each):
1. First NAVIGATE raced the session's still-CLAIMED status.
2. `<select>`'s accessible-name fallback used raw `textContent`,
   concatenating every `<option>` — produced an unresolvable locator.
3. **The in-page script's own source had an unescaped `\s` inside an
   outer JS template literal** — an unrecognized string escape that
   silently dropped the backslash, so the browser-side regex became
   `/s+/g` instead of `/\s+/g`, replacing every literal "s" with a
   space ("Test" → "Te t"). Caught by a real replay `TIMEOUT`, not by
   inspection — worth remembering if you write more inline scripts as
   JS string literals in this codebase.
4. A genuine event-ordering race between the in-page click bridge and
   Playwright's own `framenavigated` listener (two independent async
   paths) — fixed with a single Node-side FIFO queue.

**Verification**: 57/57 backend pytest (52 + 5 new), fresh `.venv`.
Frontend build clean, fresh `node_modules`. Runner `tsc --noEmit`
clean, fresh `node_modules`. Real end-to-end: attached to the runner's
own launched browser via its loopback CDP debug port (opt-in,
`RECORDER_DEBUG_PORT` env var — same mechanism `playwright codegen`
uses) to simulate a real tester interacting with it — real login (text
input + sensitive password, never persisted, confirmed by grepping the
raw SQLite DB file bytes and every log file for the literal password:
zero matches), real page transitions, a real dropdown selection, a real
checkbox, a manual checkpoint insertion, two real locator tests (one
matched, one on a since-navigated-away element honestly reported 0
matches), locator survival proven across a real viewport-resize
reflow, stop → review → edit → save as DRAFT → publish → **replayed
through the real HYB-2 runner: all 12 automated steps PASSED for real**,
correctly pausing at the `MANUAL_CHECKPOINT` (full resume is HYB-4
scope). Screenshot evidence in this session's scratchpad shows the
published revision's exact step list (with the sensitive field showing
only `${SECRET_LOGIN_PASSWORD}`, never a real value) and both replay
attempts' real outcomes (`FAILED` before the bug fixes, `PASSED`
through `WAITING_FOR_HUMAN` after).

## Current in-progress phase

**None.** HYB-4 has not been started.

## Not yet done

- HYB-4: manual checkpoints and hybrid evidence. This is where
  `MANUAL_CHECKPOINT`'s pause (proven working in both HYB-2 and HYB-3's
  replay) gets a real human-decision resume flow: `WAITING_FOR_HUMAN` →
  human PASS/FAIL/BLOCKED/N-A decision (with real actor identity +
  timestamp) → resume in the *same* browser session the runner already
  kept alive, or an honest `RUNNER_LOST` if it genuinely died. Also
  where the `HYB-1-GAP-ANALYSIS-REFRESH.md` evidence-reuse decision
  gets its `checkpoint_decision_id` link once a checkpoint-decision
  table exists (the `EvidenceItem.workflow_run_id`/
  `workflow_step_run_id` columns from HYB-2 are already there and
  already proven working — HYB-3's own replay uploaded no evidence
  since none of its steps were `SCREENSHOT`, but HYB-2's original
  verification already proved that path end-to-end).
- HYB-5: timing, reports, `HYBRID_RUNNER_THREAT_MODEL.md`, recovery
  docs, user guides, 50+-step realistic workflow verification.

## Why stopped here

Same reasoning as the prior two stops in this delivery: HYB-4 (real
human-decision resume within a live, already-paused browser session,
decision-conflict protection, honest lost-session recovery) is another
substantial, safety-critical subsystem — this is the phase where "a
later automated step must never override a human FAIL" actually gets
implemented and needs to be proven, not just asserted. It deserves its
own full build-and-verify pass rather than being compressed into the
same session as HYB-3's real debugging (four real bugs found and fixed
this session already). Deliberate stop at a clean phase boundary per
the user's own documented fallback instruction, applied proactively.

## Exact next implementation step

1. Read this file in full, and `docs/ROADMAP.md`'s HYB-2/HYB-3 entries
   — the `MANUAL_CHECKPOINT` pause mechanics (runner posts
   `CHECKPOINT_WAITING`, sets `WAITING_FOR_HUMAN`, exits its execution
   loop cleanly without calling `/complete`) already exist and are
   proven; HYB-4 builds the *resume* side on top, it doesn't rebuild
   the pause side.
2. Read `docs/Autonomous hybird prompt.md`'s HYB-4 section in full —
   note the explicit trust-model requirements: a human FAIL must never
   become an automatic PASS later; every decision needs real identity +
   timestamp; decision-conflict protection (two testers racing to
   decide the same checkpoint) is required, not optional.
3. Design a `CheckpointDecision` model (project-scoped) — likely very
   close in shape to the HYB-0 spike's `HybridCheckpointDecision`
   (append-only, one row per decision, `decided_by`/`decided_at`) but
   tied to `WorkflowRun`/`WorkflowStepRun` instead of the spike's
   `HybridRun`. Add `EvidenceItem.checkpoint_decision_id` (nullable,
   additive) once this table exists — this is the column
   `HYB-1-GAP-ANALYSIS-REFRESH.md` deferred specifically to this phase.
4. The resume protocol: a `POST /workflow-runs/{id}/checkpoint-decision`
   (user session, not runner token) records the decision; the *runner*
   (which has been polling/heartbeating while paused, keeping its
   lease alive and its browser session alive) observes the decision on
   its next poll and either continues executing subsequent steps
   (PASS) or calls `/complete` with the decision's outcome (FAIL/
   BLOCKED/N-A) — mirroring HYB-0's `waitForHumanDecision` pattern but
   against the real `WorkflowRun` protocol instead of the spike's
   `HybridRun` one.
5. Decision-conflict protection: the decision endpoint must reject a
   second decision once the run has already left `WAITING_FOR_HUMAN`
   (same "first commit wins" pattern already used elsewhere in this
   app, e.g. quota race self-eviction).
6. Honest lost-session handling: if the runner's lease expires while
   `WAITING_FOR_HUMAN` (currently `WORKFLOW_RUN_LEASED_STATUSES`
   deliberately excludes `WAITING_FOR_HUMAN` from lease tracking — this
   needs revisiting for HYB-4, since a runner that crashed while paused
   needs to be detected too, just on a different/longer timeout than
   the active-execution lease).
7. Full gate: backend pytest, frontend build, runner build/typecheck,
   then a real headed-browser + real runner verification: pause at a
   checkpoint, make a real PASS decision, confirm the *same* browser
   session resumes (not a fresh restart) and continues; repeat with a
   real FAIL decision and confirm a later automated step genuinely
   cannot overwrite it; simulate the runner dying while paused and
   confirm honest `RUNNER_LOST` handling, not a fabricated continuation.
8. Update `docs/ROADMAP.md`, write a fresh
   `docs/hybrid/SESSION_HANDOFF.md`, commit, push to
   `feature/hybrid-mvp`, record the hash, proceed to HYB-5.

## Exact commands to resume

```bash
cd d:/git/PM-QA-Again
git checkout feature/hybrid-mvp
git pull origin feature/hybrid-mvp
git log --oneline -5   # confirm HYB-3's commit is at or near HEAD

# Backend
cd backend
python -m venv .venv
./.venv/Scripts/pip install -r requirements-dev.txt
./.venv/Scripts/python -m pytest -q   # expect 57 passed

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

To manually re-verify HYB-3's real recording (optional, already proven
this session): start backend+frontend, create a project/workflow via
curl, issue a runner token, write `runner/.env` (gitignored) with
`RECORDER_DEBUG_PORT=9223` plus the usual `BACKEND_BASE_URL`/
`PROJECT_SLUG`/`RUNNER_TOKEN`/`TARGET_BASE_URL`, `npm run record` in
one terminal, create a recording session via the frontend's "Start
Recording" button, then `chromium.connectOverCDP('http://127.0.0.1:9223')`
from a separate script to simulate a tester interacting with the
recorder's browser window.

## Continuation prompt (copy-paste into a fresh session)

```
Continue the QA-Again Hybrid MVP delivery. Read
docs/hybrid/SESSION_HANDOFF.md in full first -- it has the exact
current state, what HYB-1/HYB-2/HYB-3 completed and verified (including
four real bugs found via an actual end-to-end recording+replay run, not
code review), and the precise next step. Branch is feature/hybrid-mvp.
Do not start over or re-verify HYB-1/HYB-2/HYB-3 (already done: 57/57
backend tests, frontend build clean, runner typecheck clean, a real
Node.js recorder process really captured a real tester's interactions
in a real separate Chromium window including a genuinely sensitive
password field -- confirmed never persisted anywhere -- and the saved,
published recording replayed successfully through the real HYB-2
runner). Begin HYB-4 (manual checkpoints and hybrid evidence) per
docs/Autonomous hybird prompt.md's HYB-4 section, following the same
discipline as HYB-1/HYB-2/HYB-3: real FastAPI/SQLite/Node.js/
TypeScript/Playwright behavior only, no mocked output as completion
evidence, full backend/frontend/runner gates plus real-browser
verification (including proving a human FAIL cannot later be
overwritten by automation, and honest RUNNER_LOST handling if the
runner dies mid-pause) before considering the phase done. Commit and
push HYB-4 separately. Release Closure's three human-operated checks
remain unresolved and the project remains NOT PRODUCTION READY
regardless of hybrid progress -- do not claim otherwise.
```
