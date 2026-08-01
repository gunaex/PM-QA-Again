# Session Handoff — Hybrid MVP delivery, paused after HYB-4

Written 2026-08-02. This is a **deliberate clean stop between phases**,
not a crash or a discovered blocker — see "Why stopped here" below.
Supersedes the previous version of this file (written after HYB-3).

## Current state

- **Branch**: `feature/hybrid-mvp`
- **HYB-1 commit**: `8d64495`
- **HYB-2 commit**: `0071a23`
- **HYB-3 commit**: `6c4a3f1`
- **HYB-4 commit**: `acbe56e` (pushed to `origin/feature/hybrid-mvp`).
- **`main`** is at `bb2f539` — unaffected; all hybrid work lives only on
  `feature/hybrid-mvp`.
- **`track-a-baseline` tag**: `bb2f539`.
- Working tree: clean except `docs/Autonomous hybird prompt.md` (the
  user's own file, intentionally left untouched/unstaged throughout).

## HYB-1, HYB-2, HYB-3 — complete, unchanged, not re-verified this session

See prior handoff content preserved in git history (`8d64495`,
`0071a23`, `6c4a3f1`) and `docs/ROADMAP.md`. Do not redo, rewrite, or
re-verify.

## HYB-4 — complete and verified this session

Full design/implementation detail lives in
[HYB-4-CHECKPOINTS.md](HYB-4-CHECKPOINTS.md) (state machine, decision-
conflict protection, paused-lease mechanics, lost-runner/lost-browser
table, operator/tester instructions) and `docs/ROADMAP.md`'s HYB-4
entry (full file-by-file detail). Summary:

**Backend** (additive only): new `WorkflowCheckpointDecision` table
(append-only, one row per decision, `source` always `HUMAN`,
server-derived identity/timestamp). Decision-conflict protection is the
same transaction that inserts the decision also flipping `run.status`
away from `WAITING_FOR_HUMAN` — a racing second decision finds it
already moved and gets `409`, never a silent overwrite. Idempotency via
`idempotency_key`. Reason validation and NOT_APPLICABLE admin-review
mirror `cycle_results.py` exactly. The paused lease
(`WAITING_FOR_HUMAN`/`RESUMING`) now renews on a 300s timeout instead of
the 60s active-execution one, using the *same* `lease_token` throughout
— a resume never needs a fresh claim. New endpoints: `GET checkpoint`
(full review context in one call), `POST checkpoint-decision`, `POST
checkpoint-decisions/{id}/review`, `POST checkpoint-resume`
(lease-gated — a different runner process cannot fabricate a resume).
`EvidenceItem.checkpoint_decision_id` and `Defect.workflow_run_id`/
`workflow_step_run_id`/`checkpoint_decision_id` are additive nullable
links — no parallel evidence or defect subsystem.

**Runner**: the `MANUAL_CHECKPOINT` branch in `executor.ts` no longer
closes the browser — it captures/uploads a real screenshot, posts
`CHECKPOINT_WAITING`, then polls in `waitForHumanDecision()` (keeps
heartbeating, checks `page.isClosed()` for honest crash detection,
checks `cancel_requested`). On `RESUMING` it calls `/checkpoint-resume`
and continues the *same* step loop against the *same* `page`/`browser`
objects.

**Frontend**: `CheckpointPanel.jsx` (new), rendered inline in
`WorkflowDetail.jsx`'s expanded-run view. Reuses `EvidenceGallery`/
`AnnotationEditor` unchanged (just tagged with run/step-run ids) and the
existing defect create/update endpoints — no parallel evidence viewer,
no parallel defect UI.

**Verification**: 69/69 backend pytest (57 + 12 new, covering PASS-
resume, FAIL-is-terminal-and-cannot-be-overwritten, BLOCKED/
NOT_APPLICABLE reason validation and admin review, decision conflict,
idempotent retry, `RUNNER_LOST` while paused via lease-duration
monkeypatching, LOCKED-cycle rejection, defect provenance, wrong-lease
resume rejection). Frontend build clean. Runner `tsc --noEmit` clean.
**Real end-to-end, not mocked**: real FastAPI/SQLite backend, real
Node.js/TypeScript runner, real headed Chromium, driven through the real
HTTP API to simulate a human tester. Three real runs against a workflow
with an automated step before and after a `MANUAL_CHECKPOINT`:
(1) **PASS + resume** — pre-checkpoint steps set a `localStorage` marker
and asserted it; runner paused and uploaded a real 7,720-byte screenshot
(`evidence_source=RUNNER`); a real human PASS decision was submitted
with real identity/timestamp; the *same* runner process observed
`RESUMING`, resumed, and the post-checkpoint step found the marker
**still set** — only possible if the in-memory browser context genuinely
survived the pause; run reached `PASSED`, full HUMAN→RUNNER
provenance-tagged event trail. (2) **FAIL is terminal** — a human FAIL
ended the run `FAILED`; a racing second decision (simulating another
tester or a retry) got `409` and did not overwrite it; the runner
observed the terminal status and correctly declined to resume, never
executing the two post-checkpoint steps. (3) **Cancellation while
paused** — `cancel_requested` was set on a paused run; the runner's poll
loop observed it and self-completed `CANCELLED`. Every scenario's full
event/decision/step-run history was independently confirmed via the
API. `runner/.env` (used only for this verification, holding a real
issued runner token) is gitignored and was deleted after the session.

## Current in-progress phase

**None.** HYB-5 has not been started.

## Not yet done

- HYB-5: timing, reports, recovery, security, and handover — see
  `docs/ROADMAP.md`'s HYB-5 bullet and the full requirement list in
  `docs/Autonomous hybird prompt.md`'s HYB-5 section (queue/claim/
  browser-startup/per-step/checkpoint-wait/resume/upload timing; timing
  trends; machine-vs-human provenance reports; locator-failure and
  runner-reliability reporting; hybrid Excel/ZIP export with real
  evidence bytes and full manifest links; `docs/
  HYBRID_RUNNER_THREAT_MODEL.md`; runner credential theft/revocation/
  replay/duplicate-job/fake-event/secret-leakage/unauthorized-decision
  tests; installation and credential-rotation docs; stuck-job/lost-run
  recovery; a clean-environment rehearsal; a 50+-step workflow;
  multiple sequential runs; an evidence-heavy run; a long checkpoint
  pause; repeated locator failure; dashboard/report performance with
  historical hybrid data; role-specific guides).

## Why stopped here

Same reasoning as the three prior stops in this delivery: HYB-5 is
another substantial, distinct body of work (timing infrastructure across
every layer, a threat model with its own dedicated adversarial test
suite, export format changes, multi-role documentation, a deliberately
large 50+-step realistic workflow run) — it deserves its own full
build-and-verify pass rather than being compressed into the same session
as HYB-4's real pause/resume/conflict/cancellation verification.
Deliberate stop at a clean phase boundary per the user's own documented
fallback instruction, applied proactively — same discipline as every
prior phase boundary in this delivery.

## Exact next implementation step

1. Read this file in full, `docs/hybrid/HYB-4-CHECKPOINTS.md`, and
   `docs/ROADMAP.md`'s HYB-1–HYB-4 entries.
2. Read `docs/Autonomous hybird prompt.md`'s HYB-5 section in full —
   it is long and covers five distinct areas (timing, reports, recovery,
   security, handover); consider whether it's worth splitting into
   sub-milestones within the HYB-5 session rather than one monolithic
   pass, given its size relative to HYB-1–HYB-4 combined.
3. Timing is the foundation the reports depend on — start there. Add
   timestamp columns/derivation to the existing `WorkflowRun`/
   `WorkflowStepRun`/`WorkflowCheckpointDecision` rows (most of the raw
   data — `started_at`/`ended_at`/`created_at`/`decided_at`/
   `checkpoint_waiting_since` — already exists; this is mostly about
   *deriving and reporting* durations, not capturing new raw timestamps)
   before building the report endpoints that consume them.
4. `docs/HYBRID_RUNNER_THREAT_MODEL.md` and its adversarial test suite
   (credential theft/revocation/replay/duplicate jobs/fake events/
   secret leakage/unauthorized decisions) is a distinct, security-
   critical piece — plan it as its own real Node.js/FastAPI verification
   pass, not something to write by inspection alone.
5. The 50+-step workflow, multiple sequential runs, evidence-heavy run,
   long checkpoint pause, and repeated-locator-failure scenarios are all
   real-system acceptance criteria — budget real execution time for
   them, not just code review.
6. Full gate: backend pytest, frontend lint/build, runner
   typecheck/build/tests, then the real-system verification above.
7. Update `docs/ROADMAP.md`, write a fresh
   `docs/hybrid/SESSION_HANDOFF.md`, commit, push to
   `feature/hybrid-mvp`, record the hash.
8. Release Closure's three human-operated checks (real R2 staging smoke
   test, human-operated Screen Capture acceptance, human-operated
   clipboard-paste acceptance) remain unresolved regardless of hybrid
   progress — the project remains **NOT PRODUCTION READY** until those
   are run and recorded, independent of how much of HYB-5 completes.

## Exact commands to resume

```bash
cd d:/git/PM-QA-Again
git checkout feature/hybrid-mvp
git pull origin feature/hybrid-mvp
git log --oneline -5   # confirm HYB-4's commit is at or near HEAD

# Backend
cd backend
python -m venv .venv
./.venv/Scripts/pip install -r requirements-dev.txt
./.venv/Scripts/python -m pytest -q   # expect 69 passed

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

To manually re-verify HYB-4's real checkpoint pause/resume (optional,
already proven this session): start the backend, create a project with
a published workflow containing a `MANUAL_CHECKPOINT` step, queue a run
against a real cycle result, issue a runner token, write `runner/.env`
(gitignored) with `BACKEND_BASE_URL`/`PROJECT_SLUG`/`RUNNER_TOKEN`/
`TARGET_BASE_URL`/`TARGET_EMAIL`/`TARGET_PASSWORD`, `npm run execute` —
it will pause at the checkpoint with a real headed Chromium window still
open; submit a decision via `POST /api/{slug}/workflow-runs/{id}/
checkpoint-decision` (or the real UI) and watch the same runner process
resume in the same window.

## Continuation prompt (copy-paste into a fresh session)

```
Continue the QA-Again Hybrid MVP delivery. Read
docs/hybrid/SESSION_HANDOFF.md in full first -- it has the exact
current state, what HYB-1/HYB-2/HYB-3/HYB-4 completed and verified
(including a real headed-Chromium pause/human-decision/resume run
proving the same in-memory browser session survives a checkpoint, a
real FAIL decision proven terminal against a racing second decision,
and real cooperative cancellation while paused), and the precise next
step. Branch is feature/hybrid-mvp. Do not start over or re-verify
HYB-1/HYB-2/HYB-3/HYB-4 (already done: 69/69 backend tests, frontend
build clean, runner typecheck clean). Begin HYB-5 (timing, reports,
recovery, security, and handover) per docs/Autonomous hybird
prompt.md's HYB-5 section, following the same discipline as every prior
phase: real FastAPI/SQLite/Node.js/TypeScript/Playwright behavior only,
no mocked output as completion evidence, full backend/frontend/runner
gates plus real-system verification (including the threat-model
adversarial tests and the 50+-step workflow run) before considering the
phase done. Commit and push HYB-5 separately. Release Closure's three
human-operated checks remain unresolved and the project remains NOT
PRODUCTION READY regardless of hybrid progress -- do not claim
otherwise.
```
