# HYB-5 Verification Scope — What Was and Wasn't Run This Session

Stated plainly, per this delivery's own discipline of never presenting
mocked or assumed results as completion evidence.

## What WAS run for real this session

- **Full backend pytest suite**: 95/95 passing, including 23 new HYB-5
  tests (`test_hybrid_timing_and_reports.py`,
  `test_hybrid_excel_zip_export.py`, `test_hybrid_security.py`) — all
  against the real FastAPI app (`TestClient`), real SQLite, real
  `X-Runner-Token`-authenticated client, real lease/CAS/idempotency
  mechanics. No mocked auth, no bypassed dependencies.
- **Frontend production build**: clean (`npm run build`, Vite).
- **Runner typecheck**: clean (`tsc --noEmit`).
- **A real 60-step, 2-revision, 4-run, 3-checkpoint, real-evidence,
  real-locator-failure, real-`RUNNER_LOST` scale scenario**, driven
  entirely through the real HTTP API against a real running `uvicorn`
  process with real SQLite and real filesystem `EvidenceStorage` — see
  [HYB5_SCALE_PERFORMANCE.md](HYB5_SCALE_PERFORMANCE.md) for the exact
  measurements. The runner side of this scenario used a real
  `requests.Session` presenting a real, registered `X-Runner-Token` and
  calling the exact same claim/heartbeat/step-run/evidence/checkpoint
  endpoints the real Node.js runner calls — every backend code path a
  real runner exercises was exercised for real.

## What was NOT run for real this session (honest gap, not overclaimed)

- **A literal headed-Chromium browser session against this 60-step
  fixture.** The scale scenario above proves the backend's job
  protocol, lease mechanics, checkpoint state machine, timing capture,
  and reporting/export pipeline all handle 60 real steps and 3 real
  checkpoints correctly — but it does this by having a plain HTTP client
  play the runner's part, not by launching an actual Playwright/Chromium
  process navigating a real target page. HYB-4's own prior session
  (see [HYB-4-CHECKPOINTS.md](HYB-4-CHECKPOINTS.md)) already proved real
  headed-Chromium pause/resume/FAIL/cancel end-to-end against a
  *smaller* (2-step) workflow; HYB-5 did not repeat that with the full
  Playwright browser at 60-step scale.
- **A from-scratch clean-environment rehearsal** (fresh OS-level
  `.venv`, fresh `npm install` for both frontend and runner, fresh
  `npx playwright install chromium`, starting entirely from nothing).
  This session reused the existing checked-out repo's dependencies
  (already-installed `.venv`, already-installed `node_modules` for both
  frontend and runner) rather than deleting and reinstalling everything
  from zero.
- **The three Release Closure human-operated checks** (real R2 staging
  smoke test, human-operated Screen Capture API acceptance,
  human-operated clipboard-paste acceptance) — these were never in
  HYB-5's scope; they remain unresolved regardless of hybrid progress
  and gate release status on their own.

## Why this is disclosed rather than silently skipped

The user's own instructions for this delivery are explicit: "no mocked
output as completion evidence" and "record the rehearsal in a dedicated
document" — the honest answer here is that a full clean-environment
rehearsal and a fresh headed-Chromium run at full 60-step scale did not
fit in this session's scope alongside the substantial amount of new
code, tests, and documentation HYB-5 required (timing infrastructure,
hybrid dashboard/reports, Excel/ZIP export extension, a full threat
model with its own adversarial test suite, recovery/credential-rotation
guides, and this scale measurement). Recording that gap explicitly here
is more useful to whoever picks this up next than a document that
implies more was proven than actually was.

## What this means for release status

No change: this project remains **NOT PRODUCTION READY**. HYB-5's own
completion does not (and per the user's own standing instruction,
cannot) upgrade release status — only the three Release Closure
human-operated checks listed above can do that, and none of them were
touched by this work.

## Recommended next step for whoever continues this

Run the two missing pieces as their own focused session:
1. A real headed-Chromium execution of a 50+-step workflow (can reuse
   `backend/scripts/hyb5_scale_fixture.py`'s workflow/step definitions
   as the target, but drive it with `runner/src/execution/executor.ts`
   against a real target page instead of the plain HTTP client used
   here).
2. A genuine clean-environment rehearsal following
   `docs/hybrid/SESSION_HANDOFF.md`'s "Exact commands to resume" section
   from a machine/directory with no pre-existing `.venv`/`node_modules`.
