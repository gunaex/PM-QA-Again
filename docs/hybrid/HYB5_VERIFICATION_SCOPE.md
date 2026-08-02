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

## Update (2026-08-02, later session): the headed-Chromium gap is now closed

A real headed-Chromium 72-step run (exceeding the 50+ requirement) was
executed against the real frontend/backend, with a real `MANUAL_CHECKPOINT`
pause, a real human PASS decision, a real same-session resume, a real
sensitive-variable injection, a real genuine failure, and a real
deliberate rerun-after-fix that passed. Full record:
[HYB5_REAL_BROWSER_VERIFICATION.md](HYB5_REAL_BROWSER_VERIFICATION.md).
This item is no longer an open gap.

## Update (2026-08-02, later session): clean-environment rehearsal also closed

A genuine from-scratch rehearsal (fresh `backend/.venv`, fresh
`frontend/node_modules` + build, fresh `runner/node_modules` +
typecheck, fresh SQLite) was performed, including the full functional
walkthrough end to end — bootstrap admin through Excel/ZIP
inspection and confirming Track A works with zero runner processes
running. Full record: [HYB5_CLEAN_REHEARSAL.md](HYB5_CLEAN_REHEARSAL.md).
This item is no longer an open gap either.

## What was NOT run for real this session (honest gap, not overclaimed)

Neither of the two engineering gaps from the original version of this
document remain open. What's left, unchanged, is exactly the same
category of item it always was:

- **Two of the three Release Closure human-operated checks** — the
  real R2 staging smoke test has been run and passed by the human
  operator (see `docs/RELEASE_REHEARSAL.md`); Screen Capture API
  acceptance and clipboard-paste acceptance remain outstanding and
  still gate release status on their own, regardless of hybrid or
  verification progress. These specifically require a human at a real
  browser with real OS-level permission prompts — no amount of
  automated verification substitutes for them, by design.

## What this means for release status

No change: this project remains **NOT PRODUCTION READY**. Closing
HYB-5's own engineering verification gaps does not (and per the user's
own standing instruction, cannot) upgrade release status — only the
three Release Closure human-operated checks can do that. One of three
is now done; two remain.

## Recommended next step for whoever continues this

Nothing engineering-side is outstanding from HYB-5's own scope. The
only remaining path to a production-readiness decision is the human
operator completing Screen Capture API acceptance and clipboard-paste
acceptance per `docs/RELEASE_CLOSURE.md` §2/§3.
