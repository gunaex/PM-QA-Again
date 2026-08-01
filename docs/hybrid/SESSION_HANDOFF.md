# Session Handoff — Hybrid MVP delivery, paused after HYB-1

Written 2026-08-02. This is a **deliberate clean stop between phases**,
not a crash or a discovered blocker — see "Why stopped here" below.

## Current state

- **Branch**: `feature/hybrid-mvp`
- **HEAD commit**: `8d64495` ("HYB-1 complete: workflow model and
  editor") — pushed to `origin/feature/hybrid-mvp`.
- **`main`** is at `bb2f539` ("SECURITY: remove hardcoded admin
  credentials from start.bat/start.ps1") — unaffected by HYB-1, which
  only exists on the feature branch.
- **`track-a-baseline` tag**: `bb2f539` (moved there during this
  session's history-rewrite cleanup; see below).
- Working tree: clean except `docs/Autonomous hybird prompt.md` (the
  user's own file, intentionally left untouched/unstaged throughout).

## What happened this session, in order (context for a fresh session)

1. Performance fast pass (separate from hybrid work) — committed to
   `main` earlier.
2. **Security incident + remediation**: a real admin email/password had
   been hardcoded into `start.bat`/`start.ps1` in an earlier commit.
   Removed from tracked files, then — per explicit user instruction —
   the credential was scrubbed from **all of git history** using
   `git-filter-repo --replace-text` and force-pushed. Full details,
   backup bundle location, and collaborator-resync instructions were
   reported to the user in-conversation (not duplicated here). Anyone
   picking this repo up on a second machine/clone made **before** this
   rewrite must re-clone or hard-reset to `origin/main` — their old
   local history is now divergent/orphaned.
3. `track-a-baseline` tag created (marks Track A code-complete, not a
   production-readiness claim), and
   `docs/hybrid/HYB-1-GAP-ANALYSIS-REFRESH.md` written — both on `main`.
4. User explicitly **superseded** the "HYB-1 waits on Release Closure"
   rule for this delivery (see `docs/ROADMAP.md`'s Track B section,
   2026-08-02 update) — Release Closure's three human-operated checks
   are release blockers only now, not development blockers.
5. Created `feature/hybrid-mvp` from `main` @ (then) `0a8c9ae` — this
   was **before** the history rewrite, so the branch's own history was
   rewritten along with everything else; its current base is `bb2f539`.
6. Built and fully verified **HYB-1** (see below). Committed and pushed
   separately from everything above.

## HYB-1 — completed and verified

**Acceptance criteria**: all 14 items from
`docs/Autonomous hybird prompt.md`'s HYB-1 section pass — see
`backend/tests/test_workflows.py::test_hyb1_full_acceptance_gate` for
the automated proof and the real-browser Playwright run (login → create
workflow → draft revision → all 13 step types → reorder → sensitive
`${VAR}` placeholder rejection-of-literal → link test case → publish →
confirm published can't be edited → clone → confirm original unchanged)
for the manual-flow proof.

**Files**:
- `backend/app/models.py` — `WorkflowDefinition`, `WorkflowRevision`,
  `WorkflowStep`, `WorkflowTestCaseLink`.
- `backend/app/schemas.py` — matching Pydantic schemas.
- `backend/app/routers/workflows.py` — full CRUD + reorder + publish +
  clone + links.
- `backend/app/database.py` — `PROJECT_INDEXES` additions for the new
  tables (additive, same pattern as the performance fast pass).
- `backend/app/main.py` — router wired in.
- `backend/tests/test_workflows.py` — new, 4 tests.
- `backend/tests/test_security_boundaries.py` — one-line fix (see bug
  below).
- `frontend/src/pages/WorkflowList.jsx`, `WorkflowDetail.jsx` — new.
- `frontend/src/api/client.js`, `App.jsx`, `components/Layout.jsx` —
  wired in.
- `docs/ROADMAP.md` — updated.

**Design decisions resolved** (per explicit user instruction, see
`docs/hybrid/HYB-1-GAP-ANALYSIS-REFRESH.md` §2 for the original open
questions):
1. `WorkflowTestCaseLink` carries both `test_case_id` (exact immutable
   snapshot — `TestCase` rows never change after their parent revision
   publishes, so this alone gives historical reproducibility) and
   `logical_case_key` (copied at link time, for "what's current"
   navigation).
2. Hybrid evidence will extend `EvidenceItem`/`EvidenceRevision` (not a
   parallel subsystem) — deferred to HYB-4, since HYB-1 has no
   runs/checkpoints yet to link evidence against. **Not yet
   implemented** — this is the first thing HYB-4 needs to do.

**Bug found and fixed**: `test_security_boundaries.py::
test_login_is_rate_limited` deliberately exhausts slowapi's 5/minute
login rate limit and never reset it. Since the limiter's storage is
process-global and keyed by remote address, and every `TestClient` in
the suite shares the same fake address, this silently broke *any* test
file that ran afterward (alphabetically) and needed a real login within
the same pytest process — including my new `test_workflows.py`. Fixed
with one `limiter.reset()` call at the end of that test. This was a
real, pre-existing, order-dependent flakiness bug, not something HYB-1
introduced — just newly exposed by adding another test file with
logins.

**Tests**: 45/45 backend pytest passing (was 41 before this session;
+4 new). Frontend production build clean. Both re-verified from a
fresh `.venv`/`node_modules` as the final gate before committing.

## Current in-progress phase

**None.** HYB-2 has not been started — no code, no models, no branch
state beyond what HYB-1 committed.

## Not yet done (everything from here is HYB-2 onward)

- HYB-2: runner registration (`RunnerToken`-successor with
  heartbeat/capabilities), job-claim/lease protocol, `WorkflowRun`/
  `WorkflowStepRun`/`RunnerEvent`/`RunnerLease` models, real execution
  against a published `WorkflowRevision` via the `runner/` Node.js/
  TypeScript/Playwright process (currently only has HYB-0's spike code),
  idempotency keys, duplicate-event handling, stale-runner detection,
  failure categorization.
- HYB-3: browser recorder.
- HYB-4: manual checkpoints + hybrid evidence (including the
  `EvidenceItem`/`EvidenceRevision` extension deferred above).
- HYB-5: timing, reports, `HYBRID_RUNNER_THREAT_MODEL.md`, recovery
  docs, user guides.

## Why stopped here

This is a deliberate stop at a clean phase boundary, matching the
user's own documented fallback instruction ("if the limit occurs
between phases, preserve the completed phase commit and stop before
beginning the next phase"), applied proactively rather than waiting for
a hard cutoff. HYB-2 is a substantial, genuinely new subsystem (a real
job-leasing protocol with lease expiry/idempotency/duplicate-detection,
a Node/TypeScript runner client driving real Chromium against a
published workflow, structured per-step result recording) — compressing
it into the same turn as HYB-1 plus this session's security incident
response risked exactly the "rushed code, false completion claims"
outcome the user explicitly warned against. Building it fresh, with its
own full verification pass, deserves a clean start.

## Exact next implementation step

1. Read this file and `docs/hybrid/HYB-1-GAP-ANALYSIS-REFRESH.md` (the
   latter's §1 already covers what HYB-2 needs to know about the
   completed Track A + HYB-1 state — no need to re-derive it).
2. Read `docs/hybrid/HYB-0-GAP-ANALYSIS.md` §5's decisions 1–2 and 6–7
   (REST polling not WebSockets, minimal runner-token approach, Node
   process design) — HYB-2 either builds on or deliberately supersedes
   these; the hybrid prompt's HYB-2 section asks for a fuller
   registration/heartbeat model than HYB-0's single pre-shared token, so
   expect to supersede decision 2 specifically.
3. Design `WorkflowRun`/`WorkflowStepRun`/`RunnerEvent`/`RunnerLease`
   models (project-scoped, `ProjectBase`, same pattern as everything
   else) — `WorkflowRun.workflow_revision_id` must point at a
   **PUBLISHED** revision only (reject queuing a run against a DRAFT).
4. Design the runner-registration table (master DB, like
   `RunnerToken`/`RefreshToken`) with heartbeat/capabilities/status.
5. Build the job-claim protocol endpoints, then extend `runner/`'s
   existing HYB-0 spike code to actually execute a published workflow's
   steps via Playwright against real semantic locators.
6. Full gate: backend pytest, frontend build, runner build/tests, real
   headed-browser + real runner process verification (register, claim,
   execute, upload evidence, complete — plus the lease/idempotency/
   revocation/lost-runner edge cases the prompt's HYB-2 acceptance gate
   lists).
7. Update `docs/ROADMAP.md`, commit, push to `feature/hybrid-mvp`,
   record the hash, then proceed to HYB-3 under the same discipline.

## Exact commands to resume

```bash
cd d:/git/PM-QA-Again
git checkout feature/hybrid-mvp
git pull origin feature/hybrid-mvp
git log --oneline -3   # should show 8d64495 at or near HEAD

# Backend
cd backend
python -m venv .venv
./.venv/Scripts/pip install -r requirements-dev.txt
./.venv/Scripts/python -m pytest -q   # expect 45 passed

# Frontend
cd ../frontend
npm install
npm run build   # expect clean
```

## Continuation prompt (copy-paste into a fresh session)

```
Continue the QA-Again Hybrid MVP delivery. Read
docs/hybrid/SESSION_HANDOFF.md in full first -- it has the exact
current state, what HYB-1 completed and verified, and the precise next
step. Branch is feature/hybrid-mvp, HEAD is 8d64495. Do not start over
or re-verify HYB-1 (already done: 45/45 backend tests, frontend build
clean, real headed-browser Playwright flow verified). Begin HYB-2
(runner registration and execution) per docs/Autonomous hybird
prompt.md's HYB-2 section, following the same discipline as HYB-1: real
FastAPI/SQLite/Node.js/TypeScript/Playwright behavior only, no mocked
runner output as completion evidence, full backend/frontend/runner
gates plus real-browser verification before considering the phase
done, commit and push HYB-2 separately from HYB-3 onward. Release
Closure's three human-operated checks remain unresolved and the
project remains NOT PRODUCTION READY regardless of hybrid progress --
do not claim otherwise.
```
