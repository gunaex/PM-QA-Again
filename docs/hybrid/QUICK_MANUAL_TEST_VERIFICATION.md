# Quick Manual Test UX — Real Browser Verification

Executed 2026-08-02. Verifies the Quick Manual Test UX end to end using
a real headed Chromium instance (`runner/scripts/verify-quick-manual-test.mjs`,
Playwright) against a real running backend (`uvicorn`, isolated
`DATA_DIR`) and a real running frontend (`vite`), both bound to
`localhost` (not `127.0.0.1`) so cookie-based auth works identically to
production — mixing the two hostnames breaks `SameSite=Lax` cookies
across "sites" even on the same machine, a real gotcha hit and fixed
during this verification.

## Primary measured requirement

| Path | Clicks | Elapsed time | Requirement |
|---|---|---|---|
| **After**: Dashboard → Start Testing → Quick Manual Test → active Cycle Execution | 3 | 383–571 ms (3 real runs) | < 30 s |
| **Before**: Dashboard → Test Suites → New Suite → New Revision → New Case (title/action/expected) → Publish Revision → New Cycle (name/environment) → open Cycle Execution | 9 | not applicable — a multi-minute authoring flow, since it requires writing a full suite/case before any execution screen exists | — |

The "before" flow is not a faster/slower version of the same action —
it is the only way to reach an execution screen prior to this feature,
and requires authoring a durable suite/case first. Quick Manual Test's
9× fewer clicks and ~50–100× faster time-to-first-test come from
skipping suite/case authoring entirely for the common one-off case,
while still landing in the exact same `CycleExecution` screen backed by
a real `TestCycle`/`CycleTestResult`.

## What was verified for real

| Gate | Result |
|---|---|
| Dashboard → Start Testing → Quick Manual Test → active execution | ✅ 3 clicks, well under 30s (3 runs: 383ms, 438ms, 571ms) |
| Evidence/actual-result/status controls immediately visible, no extra navigation | ✅ Upload control and PASS/NG/BLOCKED/N-A buttons present on first render |
| PASS blocked without evidence (`require_evidence_for_pass`) | ✅ rejected with evidence-related error, verified via real UI attempt |
| PASS accepted once real evidence (real PNG upload) exists | ✅ verified via API against the real `CycleTestResult` row |
| Save & Next persists current draft and advances | ✅ reached the completion summary panel on the only case |
| Run Now (real button on Suite Detail, real published suite/revision) | ✅ opened a new active cycle execution screen directly |
| Rerun FAIL/BLOCKED only (real UI button, after marking a case FAIL with a real actual-result) | ✅ navigated to a brand-new cycle, source cycle left unchanged |
| Continue Last Test (Dashboard button) | ✅ present after an in-progress quick test and an in-progress Run Now cycle both exist |
| Quick-test cycle exported via Excel | ✅ HTTP 200, real file |
| Quick-test cycle exported via ZIP | ✅ HTTP 200, real file |

## Real bugs found and fixed during this verification

None in the product code. Three issues surfaced were all in the
verification script itself:

1. **Selector collision**: `button:has-text("PASS")` matched the
   case-list status *filter* button (`STATUS_FILTERS` renders a plain
   `<button>PASS</button>` for the filter row) before the real submit
   button in the sticky action area, so the click never reached
   `submitStatus('PASS')` and the evidence-rejection check produced a
   false positive by matching unrelated "evidence" text elsewhere on
   the page. Fixed by targeting the action buttons via their `title`
   attribute (`button[title="Alt+P"]`, `button[title="Alt+F"]`), which
   only the real PASS/FAIL/BLOCKED/N-A submit buttons carry.
2. **Cross-site cookies**: backend on `127.0.0.1:8001` + frontend on
   `localhost:5174` silently dropped the session cookie on later
   requests (`SameSite=Lax` treats the two hostnames as different
   sites, even though both resolve to the same machine). Fixed by
   running both on the identical hostname (`localhost`).
3. **Async-fetch race**: the "Continue Last Test button present" check
   ran immediately after `page.goto()`, before the Dashboard's
   `getContinueLastTest()` `useEffect` fetch had resolved. Fixed with a
   short wait before asserting.

## Scope confirmation

- No parallel ad-hoc testing model was introduced — Quick Manual Test,
  Run Now, and Rerun all go through the exact same
  `create_cycle_with_snapshot()` helper used by the original
  `POST /cycles` endpoint, producing real `TestSuite` / `ScriptRevision`
  / `TestCase` / `TestCycle` / `CycleTestResult` rows.
- Evidence-required-for-PASS, append-only history
  (`CycleResultHistory`), locked-cycle rules, admin-only reopen with
  reason, audit logging, and exports all continue to apply unchanged —
  confirmed against the real quick-test cycle above.
- Quick-test suites/cycles are `is_system_generated=True`, hidden from
  the default suite/cycle lists, but fully reachable by ID and always
  included in exports regardless of the flag — confirmed above.
- The Chrome extension recorder, hybrid runner, and Reports page were
  not touched by this change.

## Reproduction

```bash
# Terminal 1 — isolated backend
cd backend
DATA_DIR=./data-quicktest-verify ADMIN_EMAIL=admin@example.com \
  ADMIN_PASSWORD=changeme123 ALLOWED_ORIGINS=http://localhost:5174 \
  .venv/Scripts/python -m uvicorn app.main:app --host localhost --port 8001

# Terminal 2 — isolated frontend
cd frontend
VITE_API_BASE_URL=http://localhost:8001 npx vite --port 5174 --host localhost

# Terminal 3
cd runner
QA_VERIFY_BACKEND=http://localhost:8001 QA_VERIFY_FRONTEND=http://localhost:5174 \
  node scripts/verify-quick-manual-test.mjs
```
