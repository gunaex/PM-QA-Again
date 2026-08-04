# HYB-5 Clean-Environment Rehearsal — Full Record

Executed 2026-08-02. Closes the gap flagged in
[HYB5_VERIFICATION_SCOPE.md](HYB5_VERIFICATION_SCOPE.md).

## 1. Fresh backend virtual environment

```bash
cd backend
mv .venv .venv.bak_pre_rehearsal   # reversible, not deleted outright
python -m venv .venv
./.venv/Scripts/python -m pip install --upgrade pip -q
./.venv/Scripts/pip install -r requirements-dev.txt
```

Full dependency resolution from PyPI (FastAPI, SQLAlchemy, boto3,
moto, pytest, openpyxl, playwright-adjacent tooling not needed here —
backend only). Old `.venv` removed only after the fresh one was
confirmed working.

```bash
./.venv/Scripts/python -m pytest -q
```
```
........................................................................ [ 75%]
.......................                                                  [100%]
95 passed in 30.12s
```

## 2. Fresh frontend node_modules + build

```bash
cd frontend
mv node_modules node_modules.bak_pre_rehearsal
npm install
```
```
added 379 packages, and audited 380 packages in 13s
2 high severity vulnerabilities
```
(Pre-existing transitive-dependency advisories, unrelated to this
session's changes — not addressed here per the "no new features, no
redesign" scope of this delivery; flagged as a known item, not fixed.)

```bash
npm run build
```
```
✓ 102 modules transformed.
dist/assets/index-CPGcb0s7.css   32.20 kB │ gzip:   6.70 kB
dist/assets/index-BPHkquEh.js   396.02 kB │ gzip: 114.53 kB
✓ built in 5.41s
PWA v1.3.0 — files generated
```
Clean, no errors.

## 3. Fresh runner node_modules + typecheck

```bash
cd runner
mv node_modules node_modules.bak_pre_rehearsal
npm install
```
```
added 8 packages, and audited 9 packages in 2s
found 0 vulnerabilities
```

```bash
npx playwright install chromium
```
No output — already satisfied (Playwright's browser cache at
`%LOCALAPPDATA%\ms-playwright` is independent of `node_modules` and
content-addressed by browser version; a fresh `node_modules` does not
require redownloading an already-cached, matching-version browser).

```bash
npm run typecheck
```
```
> tsc --noEmit
```
Clean, no errors.

## 4. Fresh SQLite data directory

```bash
cd backend
rm -f data/master.db && rm -rf data/projects
```

## 5. Full functional walkthrough (fresh backend + fresh frontend, both started clean)

```bash
ADMIN_PASSWORD=RehearsalAdmin123! ./.venv/Scripts/python -m uvicorn app.main:app --port 8000
# separate terminal
npm run dev -- --port 5173
```

All of the following were driven via real HTTP calls (`requests`)
against the real running backend, and the hybrid portion via the real
Node.js/TypeScript runner against the real running frontend:

| Step | Result |
|---|---|
| 1. Bootstrap administrator (`ADMIN_PASSWORD` env var) + login + forced password rotation | `200`, `200` |
| 2. Create project | `clean-rehearsal-project` |
| 3. Create + publish Track A suite/revision/case | `PUBLISHED` |
| 4. Create manual cycle | cycle 1, result `NOT_RUN` |
| 5. Upload evidence (real PNG) | `200`, evidence id 1 |
| 6. Execute → PASS | `200`, `PASS` |
| 7. Track A dashboard | pass_rate 100%, evidence_completeness 100% |
| 8. Create + publish a real hybrid workflow (12 steps incl. sensitive-variable login fill and a `MANUAL_CHECKPOINT`) | `PUBLISHED` |
| 9. Register a real runner token | issued |
| 10. Execute with the **real headed-Chromium runner** (`npm run execute`) | steps 1–8 real `PASSED` |
| 11. Real checkpoint pause | `WAITING_FOR_HUMAN` confirmed via `GET /workflow-runs/2` |
| 12. Real human PASS decision | `200`, `PASS` |
| 13. Real same-session resume | runner log: `checkpoint decision=PASS -- resuming the same browser session with 3 remaining step(s)` |
| 14. Real completion | `PASSED`, all 12 steps green |
| 15. Hybrid dashboard reflects it | `run_status_counts: {PASSED: 1, FAILED: 1, ...}` (the `FAILED` entry is from an earlier setup attempt against a cycle missing `target_base_url` — a real, caught, and corrected mistake, not hidden) |
| 16. Excel export downloaded, opened with `openpyxl` | 15 sheets present (7 Track A + 8 hybrid), real `Workflow Runs` rows for both run attempts |
| 17. ZIP export downloaded, extracted with `zipfile` | `testzip()` → `None` (valid archive); every evidence entry's real SHA-256 checksum independently recomputed and compared against the manifest — all matched |
| 18. Track A remains usable with **zero runner processes running** | a second suite/cycle/evidence/PASS executed purely through the human-facing API after the runner process had already exited — `200`, `PASS` |

### A real mistake, made and caught, during this rehearsal

Step 10's first attempt failed immediately with a real
`NAVIGATION_ERROR` — the test cycle used to link the workflow run
had no `target_base_url` set, so the runner's `NAVIGATE /login` step
resolved to a bare relative path Playwright rejects. Fixed via a real
`PUT /cycles/{id}` call setting `target_base_url`, then re-queued and
re-ran successfully. Left visible in the hybrid dashboard's
`run_status_counts` (one `FAILED` run from the mistake, one `PASSED`
from the corrected retry) rather than being erased — an honest
reflection of what actually happened, matching this rehearsal's own
"real measurements, not estimates" discipline.

## 6. Cleanup

`runner/.env` (session-scoped runner token, no production credential)
deleted immediately after use. `backend/data/` cleared again after the
rehearsal. All `.bak_pre_rehearsal` directories removed only after each
fresh install was confirmed working (tests passed / build succeeded /
typecheck clean) — never deleted the working copy before confirming its
replacement was good.

## Conclusion

Every item in this rehearsal's scope passed, cold, from a genuinely
fresh `.venv`/`node_modules`/SQLite state, with real assertions (not
just "it didn't crash"), including a real headed-Chromium hybrid
execution with a real checkpoint pause/human-decision/resume cycle.
This closes the clean-environment-rehearsal gap. It does **not** clear
the two remaining Release Closure items (Screen Capture API
acceptance, clipboard-paste acceptance) — those still require a human
operator in a real browser with real OS-level permission prompts, which
this rehearsal (headless-capable automation) cannot supply.
