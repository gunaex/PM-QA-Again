# Hybrid Recovery Runbook (HYB-5)

Operator-facing procedures for every failure mode a hybrid workflow run
can hit. The guiding rule throughout, matching
[HYBRID_RUNNER_THREAT_MODEL.md](../HYBRID_RUNNER_THREAT_MODEL.md) §11:
**recovery never fabricates a successful continuation and never reuses
a dead browser session.** Every procedure below either (a) already
happens automatically via the lease-expiry sweep, or (b) is a real,
auditable admin action against the real API — never a direct database
edit.

## Quick reference

| Situation | Detection | Recovery |
|---|---|---|
| Stale runner / expired lease | `lease_expires_at < now` while `CLAIMED`/`STARTING`/`RUNNING`/`WAITING_FOR_HUMAN`/`RESUMING` | Automatic — next request to any endpoint sweeps it to `RUNNER_LOST` |
| Runner lost before claim | Run stays `QUEUED` far longer than expected | See "Stuck QUEUED" below |
| Runner lost during execution | Run stuck `CLAIMED`/`STARTING`/`RUNNING`, no recent `HEARTBEAT` event | Automatic sweep once lease expires (≤60s) |
| Runner lost while paused | Run stuck `WAITING_FOR_HUMAN`/`RESUMING`, no recent `HEARTBEAT` | Automatic sweep once the 300s paused lease expires |
| Chromium crash (runner still connected) | Runner self-reports via `POST /complete` with `status=RUNNER_LOST` | Already handled — see HYB-4's `waitForHumanDecision()`'s `page.isClosed()` check |
| Server restart | In-flight requests fail; runs already `CLAIMED` etc. simply await their lease's natural expiry | No special action — SQLite state survives a restart; nothing to replay |
| Duplicate job claim | N/A by construction | `/claim` is one atomic pull-oldest-QUEUED transaction — a second racing runner gets `{"claimed": false}` |
| Duplicate runner event | N/A by construction | `idempotency_key` uniqueness returns the original row |
| Duplicate human decision | N/A by construction | Decision-conflict CAS: a racing second decision gets `409` |
| Stuck QUEUED | `GET /workflow-runs?status=QUEUED`, compare `created_at` age | Cancel and requeue, or investigate why no runner is claiming |
| Stuck CLAIMED | `GET /workflow-runs?status=CLAIMED`, compare `updated_at`/lease age | Wait for lease expiry (≤60s) or admin-cancel |
| Stuck WAITING_FOR_HUMAN | `GET /workflow-runs?status=WAITING_FOR_HUMAN`, compare `checkpoint_waiting_since` age | This is expected to be long (a human is deciding) — only act if the runner's lease has also expired |
| Cancellation | N/A | `POST /workflow-runs/{id}/cancel` — immediate if `QUEUED`, cooperative (`cancel_requested`) otherwise |
| Safe retry | N/A | Re-queue a fresh run against the same revision — a run is never mutated in place to "retry" |
| Deliberate rerun | N/A | `POST /workflow-runs` again — always creates a new `WorkflowRun` row (new id), never reuses an old one |
| Evidence reconciliation | Compare `EvidenceItem` rows against `EvidenceStorage` object keys | Reuses Track A's existing reconciliation tooling — see [EVIDENCE_STORAGE_LIFECYCLE.md](../EVIDENCE_STORAGE_LIFECYCLE.md); hybrid evidence rows are ordinary `EvidenceItem` rows, no separate reconciliation path needed |
| Orphaned storage objects | Same as above | Same tooling — a hybrid upload failing after `storage.put()` but before the DB commit triggers the same compensating delete already used for Track A uploads (see `workflow_runs.py::upload_run_evidence`'s `except` block) |
| Revoked runner credentials | N/A | `PUT /api/runner-tokens/{id}/revoke` — checked on every subsequent runner call, not just at claim |
| Runner credential rotation | N/A | See [RUNNER_CREDENTIAL_ROTATION.md](RUNNER_CREDENTIAL_ROTATION.md) |

## Detailed procedures

### 1. Stale runner / expired lease (automatic)

`workflow_runs.py::_expire_stale_leases` runs at the top of every
workflow-run endpoint (claim, heartbeat, events, step-runs, complete,
checkpoint-*, list, get). Any run whose `lease_expires_at` has passed
while in a leased status
(`CLAIMED`/`STARTING`/`RUNNING`/`WAITING_FOR_HUMAN`/`RESUMING`) is moved
to `RUNNER_LOST`, `ended_at` is set, the lease is cleared, and a
`RUNNER_LOST` event (actor `SYSTEM`) is appended. **No operator action
needed** — this is a lazy sweep, not a cron job, so it fires the moment
anyone (human or runner) next touches the project.

Active-execution leases (`CLAIMED`/`STARTING`/`RUNNING`) use a 60s
window (`LEASE_DURATION_SECONDS`); paused leases
(`WAITING_FOR_HUMAN`/`RESUMING`) use a 300s window
(`PAUSED_LEASE_DURATION_SECONDS`) — long enough that a human taking a
minute or two to review a checkpoint never false-positives as lost.

### 2. Stuck QUEUED run

A run stuck `QUEUED` means no runner process is polling `/claim` for
that project (runner offline, misconfigured `PROJECT_SLUG`, or every
registered runner's token has been revoked).

```
GET /api/{slug}/workflow-runs?status=QUEUED
```

Check `created_at` age. If a runner should have picked it up:
1. Confirm a runner process is actually running and pointed at this
   project (`runner/.env`'s `PROJECT_SLUG`).
2. `GET /api/runner-tokens` and confirm at least one token for this
   effort is not `REVOKED` and has a recent `last_heartbeat_at`.
3. If genuinely abandoned, `POST /workflow-runs/{id}/cancel` (immediate
   for `QUEUED` — no runner to cooperate with) and re-queue if the run
   is still needed.

### 3. Stuck CLAIMED/STARTING/RUNNING run

Compare the run's `updated_at` (or the most recent `HEARTBEAT` event's
timestamp — see the timing report,
`GET /hybrid-reports/timing/runs/{id}`) against the 60s active lease
window. If the lease hasn't expired yet, wait — the sweep will resolve
it automatically within a minute of the runner going quiet. If it's
been much longer than that and the run is still showing a non-terminal
status, something prevented the sweep from firing (e.g. no one has hit
any endpoint for this project) — simply issuing any `GET
/workflow-runs/{id}` triggers the sweep immediately.

### 4. Stuck WAITING_FOR_HUMAN run

This is often *expected* to be long — a human may take real time to
review a checkpoint (HYB-5's `checkpoint_waiting_summary` /
`checkpoint_waiting_duration_seconds` reports this exact distribution
for informational purposes, never as a hard cutoff). Only investigate
if:
- the runner's own lease has also expired (300s with no heartbeat) — it
  will already have been swept to `RUNNER_LOST` automatically, or
- a human genuinely will never decide (e.g. the reviewer left the
  organization) — an admin can `POST /workflow-runs/{id}/cancel`, which
  sets `cancel_requested`; if the runner process is still alive and
  polling, it observes this and self-completes `CANCELLED` on its next
  poll. If the runner is already gone, the paused lease will expire on
  its own within 300s and the run becomes `RUNNER_LOST` instead —
  either way, no fabricated outcome.

### 5. Cancellation

`POST /workflow-runs/{id}/cancel`:
- `QUEUED` → cancelled immediately (`CANCELLED`, no runner involved).
- Any leased status → cooperative: `cancel_requested=True` is set; the
  runner observes it on its next per-step check or checkpoint poll loop
  and calls `/complete` with `status=CANCELLED` itself. The backend
  never force-terminates a run out from under a runner that's still
  connected — that would risk a race with in-flight work the runner
  doesn't know was abandoned.

### 6. Safe retry vs. deliberate rerun

There is no "retry in place" endpoint, deliberately: `WorkflowRun` rows
are never mutated back to `QUEUED` once terminal. To retry or rerun,
queue a fresh run against the same (or a newer, republished)
`workflow_revision_id` via `POST /workflow-runs` — this always creates a
new row with its own id, timing history, step-run history, and event
log, so historical timing/reporting data for the original attempt is
never overwritten (see [ROADMAP.md](../ROADMAP.md)'s "preserve
historical runs" requirement).

### 7. Evidence reconciliation and orphaned storage objects

Hybrid runner-uploaded evidence is stored in the exact same
`EvidenceItem` table and `EvidenceStorage` abstraction as Track A's own
tester-uploaded evidence — there is no separate hybrid evidence
reconciliation process to build or run. Follow
[EVIDENCE_STORAGE_LIFECYCLE.md](../EVIDENCE_STORAGE_LIFECYCLE.md)
unchanged; it already covers both sources.

If a runner's evidence upload fails after the storage write but before
the DB commit, `workflow_runs.py::upload_run_evidence`'s `except` block
attempts a compensating delete of the orphaned object and logs loudly
(`ORPHANED EVIDENCE OBJECT ...`) if that cleanup itself fails — grep
backend logs for that exact string to find any that need manual
cleanup.

### 8. Server restart

SQLite state (runs, step-runs, events, decisions) survives a restart —
nothing is held only in backend process memory. In-flight HTTP requests
at the moment of restart simply fail (the runner/frontend retries or
observes the error); any run left `CLAIMED`/`RUNNING`/etc. by an
in-flight request that never completed will be swept to `RUNNER_LOST`
once its lease naturally expires, exactly as in the stale-runner case —
**no special server-restart recovery code exists, or is needed**, given
the lease mechanism already treats "went quiet for any reason" the same
way regardless of cause.
