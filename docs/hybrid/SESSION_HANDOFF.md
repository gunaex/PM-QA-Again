# Session Handoff — HYB-5 complete

Written 2026-08-02. Supersedes the previous version of this file
(written after HYB-4).

## Current state

- **Branch**: `feature/hybrid-mvp`
- **HYB-1 commit**: `8d64495`
- **HYB-2 commit**: `0071a23`
- **HYB-3 commit**: `6c4a3f1`
- **HYB-4 commit**: `acbe56e`
- **HYB-5 commit**: see the commit this file was last updated alongside
  (recorded in the commit message and the final delivery report).
- **`main`** is at `bb2f539` — unaffected; all hybrid work lives only on
  `feature/hybrid-mvp`.
- **`track-a-baseline` tag**: `bb2f539`.

## HYB-1 through HYB-4 — complete, unchanged, not redesigned this session

See prior handoff content preserved in git history and
`docs/ROADMAP.md`'s HYB-1–HYB-4 entries. Not touched this session beyond
reading them for context.

## HYB-5 — complete this session

Full detail lives in `docs/ROADMAP.md`'s HYB-5 entry (file-by-file) and
these dedicated documents:

- [`docs/HYBRID_RUNNER_THREAT_MODEL.md`](../HYBRID_RUNNER_THREAT_MODEL.md)
  — full threat coverage, each claim backed by a named test.
- [`docs/hybrid/RECOVERY_RUNBOOK.md`](RECOVERY_RUNBOOK.md) — every
  recovery scenario the spec listed.
- [`docs/hybrid/RUNNER_CREDENTIAL_ROTATION.md`](RUNNER_CREDENTIAL_ROTATION.md)
- [`docs/hybrid/HYBRID_GUIDES.md`](HYBRID_GUIDES.md) — architecture
  overview + workflow-author/recorder/tester/checkpoint-reviewer/runner-
  installation/runner-operator/reporting-export guides, consolidated
  into one document (a deliberate, documented scope decision).
- [`docs/hybrid/HYB5_SCALE_PERFORMANCE.md`](HYB5_SCALE_PERFORMANCE.md)
  — real 60-step/2-revision/4-run measurement.
- [`docs/hybrid/HYB5_VERIFICATION_SCOPE.md`](HYB5_VERIFICATION_SCOPE.md)
  — **read this one first if continuing** — the exact honest accounting
  of what was and wasn't verified for real this session.

**Summary**: timing derivation (`backend/app/hybrid_timing.py`) reads
existing HYB-2/HYB-4 timestamps/events — no schema change needed except
one additive nullable column (`EvidenceItem.upload_duration_ms`).
Hybrid dashboard/reports (`backend/app/hybrid_metrics.py`,
`backend/app/routers/hybrid_reports.py`, new `/hybrid-reports` prefix,
new frontend page) never touch Track A's own dashboard/reports.
Excel export gained 8 new hybrid sheets appended after the original 7
Track A sheets (unchanged). ZIP export's manifest gained a `hybrid`
section linking every entity by id, plus checksum verification on every
packaged evidence file. A full adversarial security test suite (17
tests, `backend/tests/test_hybrid_security.py`) backs the new threat
model doc — including a **documented, not newly-introduced**
cross-project-runner-access trust boundary (RunnerToken has always been
a global credential, same as every human user; HYB-5 made this an
explicit tested fact rather than silently changing or ignoring it).
Recovery/credential-rotation are mostly "already handled, now written
down" — the lease-expiry sweep, decision-conflict CAS, and idempotency
keys already built in HYB-2/HYB-4 cover almost every scenario the spec
listed; one new operator affordance (`GET /workflow-runs?status=...`
filter) was added.

**Verification gate this session**: full backend pytest **95/95**
(69 existing + 23 new + 3 modified assertions), frontend build clean,
runner `tsc --noEmit` clean. A real 60-step/2-revision/4-run/3-checkpoint
scale scenario ran against a real `uvicorn` process with real SQLite and
real filesystem `EvidenceStorage`, driven by a real `X-Runner-Token`-
authenticated HTTP client exercising every backend code path a real
runner uses — full measurements in `HYB5_SCALE_PERFORMANCE.md`.

**Explicitly not done this session** (see `HYB5_VERIFICATION_SCOPE.md`
for the full accounting — stated here so it can't be missed):
1. A literal headed-Chromium Playwright run of the 60-step fixture
   (the scale scenario used a plain HTTP client presenting a real
   runner token instead of an actual browser process).
2. A from-scratch clean-environment rehearsal (fresh `.venv`/
   `node_modules` from zero) — this session reused the already-installed
   dependencies from the existing checkout.

Both are real gaps, not fabricated as done. Recommended as the very
next session's starting point.

## Current in-progress phase

**None.** HYB-5 is the last planned phase in
`docs/Autonomous hybird prompt.md`'s scope. What remains before any
production-readiness claim is Release Closure's three human-operated
checks (unchanged by any hybrid work, see below) plus the two
verification gaps above if a fuller confidence level is wanted before
relying on this at 50+-step real-browser scale.

## Why stopped here

HYB-5's own scope (13 sections in the source prompt) is now fully
implemented and gated by a passing test suite, a real (if HTTP-client-
driven rather than full-browser) scale scenario, and complete
documentation. The two items in "explicitly not done" are the honest
boundary of this session's real, verified work — continuing to claim
more without actually running a real headed-browser 50+-step session or
a real clean-environment install would cross into exactly the kind of
fabricated completion evidence this delivery has avoided at every prior
phase boundary.

## Release status

**NOT PRODUCTION READY.** Unchanged by HYB-5. The three Release Closure
blockers (real Cloudflare R2 staging smoke test, human-operated Screen
Capture API acceptance, human-operated clipboard-image paste acceptance)
remain unresolved and untouched by any hybrid work, HYB-0 through
HYB-5.

## Exact commands to resume

```bash
cd d:/git/PM-QA-Again
git checkout feature/hybrid-mvp
git pull origin feature/hybrid-mvp
git log --oneline -6   # confirm HYB-5's commit is at or near HEAD

# Backend
cd backend
./.venv/Scripts/python -m pytest -q   # expect 95 passed

# Frontend
cd ../frontend
npm run build   # expect clean

# Runner
cd ../runner
npm run typecheck   # expect clean
```

To reproduce the HYB-5 scale/performance measurement:
```bash
cd backend
rm -f data/master.db && rm -rf data/projects   # fresh, never committed
ADMIN_PASSWORD=changeme123 ./.venv/Scripts/python -m uvicorn app.main:app --port 8000
# separate terminal:
cd backend && ./.venv/Scripts/python scripts/hyb5_scale_fixture.py
```

## Continuation prompt (copy-paste into a fresh session)

```
Continue the QA-Again Hybrid MVP delivery. Read
docs/hybrid/SESSION_HANDOFF.md in full first, then
docs/hybrid/HYB5_VERIFICATION_SCOPE.md -- HYB-1 through HYB-5 are all
complete (95/95 backend tests, frontend build clean, runner typecheck
clean); do not redesign any of them. Two real gaps remain from HYB-5's
own session: (1) a literal headed-Chromium Playwright run of a 50+-step
workflow (the existing scale scenario in
backend/scripts/hyb5_scale_fixture.py used a plain HTTP client instead
of a real browser -- reuse its workflow/step definitions but drive them
through runner/src/execution/executor.ts against a real target page),
and (2) a genuine from-scratch clean-environment rehearsal (fresh
.venv/node_modules, following SESSION_HANDOFF.md's "Exact commands to
resume"). Do both for real, with real measurements, not mocked. Release
Closure's three human-operated checks (real R2 staging smoke test,
human-operated Screen Capture acceptance, human-operated clipboard-
paste acceptance) remain unresolved regardless of hybrid progress --
the project remains NOT PRODUCTION READY until those are run and
recorded.
```
