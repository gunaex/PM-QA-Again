# HYB-5 Scale & Performance Verification

Real measurements against a real running backend, following the same
method as [PERFORMANCE_FAST_PASS.md](../PERFORMANCE_FAST_PASS.md)
(measure the real thing, don't estimate). **This does not change release
status** — the project remains **NOT PRODUCTION READY** regardless of
these results (see [ROADMAP.md](../ROADMAP.md) / Release Closure).

## Method

1. Fresh `data/` (deleted `master.db`/`projects/` before the run — never
   committed, gitignored).
2. Real `uvicorn` process, filesystem `EvidenceStorage` (local dev
   default), port 8000, fixed `ADMIN_PASSWORD` env var for a
   reproducible bootstrap login (no code change — just an env var).
3. `backend/scripts/hyb5_scale_fixture.py` (committed script; the
   database/evidence it produces is not) drives the fixture entirely
   through the real HTTP API — real workflow/revision/step creation,
   real runner-token registration, a real `X-Runner-Token`-authenticated
   client claiming/executing runs exactly like the Node.js runner does,
   real evidence uploads, real human checkpoint decisions via the same
   endpoint the UI calls.
4. Each measured endpoint is timed with `time.perf_counter()` around the
   real `requests` HTTP call (wall clock, including full ASGI + SQLite
   round-trip) — not an internal function call, not an estimate.

## Fixture built (real, not simulated)

One project (`hyb-5-scale-fixture`):
- One workflow, **60 steps** (3 `MANUAL_CHECKPOINT`s at positions 10,
  25, 40 — exceeds the 50+-step requirement).
- **Two published revisions** (`v1`, then a cloned-and-republished
  `v2`) — exercises multi-revision history.
- **4 real sequential runs**:
  1. All-steps-PASSED run through all 60 steps, including 3 real
     `MANUAL_CHECKPOINT` pauses each resolved with a real human PASS
     decision (via the same `/checkpoint-decision` endpoint the UI
     calls) and a real screenshot evidence upload per checkpoint.
  2. A run with a **real ~3-second checkpoint pause** (stands in for
     "long checkpoint pause" — `time.sleep(3)` between
     `CHECKPOINT_WAITING` and the decision, so `checkpoint_waiting_duration_seconds`
     reflects a genuine, non-trivial wait, not an instant round-trip).
  3. A run with **repeated locator failures** (2x `LOCATOR_NOT_FOUND`
     before a 3rd successful attempt on the same step) plus a real
     linked defect.
  4. A run deliberately left claimed and never heartbeat/completed —
     resolved to `RUNNER_LOST` by the real lease-expiry sweep.
- Real evidence bytes (PNG) for every checkpoint screenshot, stored via
  the real `EvidenceStorage` abstraction.

## Measured (2026-08-02, local Windows dev machine, filesystem storage)

| Endpoint | Time | Payload |
|---|---|---|
| `GET /workflows` | 8.9 ms | 252 B |
| `GET /workflow-runs` (list, 4 runs) | 10.7 ms | 1,859 B |
| `GET /workflow-runs/{id}` (detail, 60-step run, 3 checkpoints) | 10.3 ms | 50,041 B |
| `GET /hybrid-reports/dashboard` | 22.1 ms | 5,315 B |
| `GET /hybrid-reports/locator-failures` | 6.3 ms | 116 B |
| `GET /hybrid-reports/failure-categories` | 6.5 ms | 206 B |
| `GET /hybrid-reports/workflows-frequent-failures` | 7.5 ms | 117 B |
| `GET /hybrid-reports/slowest-steps` | 23.8 ms | 1,049 B |
| `GET /hybrid-reports/timing/runs/{id}` (60-step run) | 11.5 ms | 18,123 B |
| `GET /hybrid-reports/timing/run-trend` | 6.5 ms | 517 B |
| `GET /hybrid-reports/timing/step-trend` | 8.5 ms | 122 B |
| `GET /cycles/{id}/export/excel` (incl. 8 hybrid sheets) | 89.0 ms | 23,574 B |
| `GET /cycles/{id}/export/zip` (incl. real evidence bytes + hybrid manifest) | 94.5 ms | 26,442 B |

## Assessment

Every measured endpoint stayed well under 100ms against a 60-step,
multi-revision, multi-run, checkpoint-heavy, locator-failure-heavy
dataset with real evidence — no N+1 blowup was observed even in the
per-run `hybrid_timing.run_timing()` path (called once per run in both
the dashboard and the Excel "Timing Trends" sheet, each of which does a
handful of indexed queries per run rather than per step). The heaviest
endpoints (Excel/ZIP export) are still sub-100ms because export
generation reuses the same query patterns as the lighter report
endpoints — no separate expensive code path.

**Caveat, stated plainly**: this is a single local run against a
4-run/60-step dataset, not a load test (no concurrent clients, no
hundreds of runs). It demonstrates the query patterns don't have an
obvious N+1/unbounded-payload defect at this scale — it does not
demonstrate behavior at, say, 10,000 historical runs. See "Known
limitations" in the final HYB-5 report for what this does and doesn't
prove.

## Reproducing this measurement

```bash
cd backend
rm -f data/master.db && rm -rf data/projects   # fresh state, never committed
ADMIN_PASSWORD=changeme123 ./.venv/Scripts/python -m uvicorn app.main:app --port 8000
# separate terminal:
cd backend && ./.venv/Scripts/python scripts/hyb5_scale_fixture.py
```
