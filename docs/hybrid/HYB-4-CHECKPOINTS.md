# HYB-4 — Manual checkpoints: state machine, protocol, and operator guide

Companion to `docs/ROADMAP.md`'s HYB-4 entry and
`docs/Autonomous hybird prompt.md`'s HYB-4 section. This is the detail
doc; ROADMAP.md is the index.

## Critical invariant

**A human FAIL, BLOCKED, or NOT_APPLICABLE decision is terminal and can
never be overwritten or converted to PASS by later automation, a racing
request, or a runner reconnecting.** Every mechanism below exists to
protect this one property.

## `WorkflowRun` state machine (HYB-4 additions in bold)

```
QUEUED
  → CLAIMED (runner /claim)
  → STARTING → RUNNING (first step-run created)
  → **WAITING_FOR_HUMAN** (runner posts CHECKPOINT_WAITING at a MANUAL_CHECKPOINT step)
      → **RESUMING** (human PASS decision — atomic with the decision insert)
          → RUNNING (runner calls /checkpoint-resume, same browser session)
              → PASSED | FAILED (further automated steps)
      → FAILED (human FAIL decision — terminal, atomic with the decision insert)
      → BLOCKED (human BLOCKED decision — terminal)
      → NOT_APPLICABLE (human NOT_APPLICABLE decision — terminal, enters admin review)
      → CANCELLED (cancel_requested observed by the runner's pause-poll loop)
      → RUNNER_LOST (paused lease expired — runner went silent while paused)
  → PASSED | FAILED | BLOCKED | CANCELLED | RUNNER_LOST | SYSTEM_ERROR (terminal)
```

Terminal statuses (`WORKFLOW_RUN_TERMINAL_STATUSES`): `PASSED`, `FAILED`,
`BLOCKED`, `NOT_APPLICABLE`, `CANCELLED`, `RUNNER_LOST`, `SYSTEM_ERROR`.
No further mutation, no further lease, no route back to `RUNNING` except
a deliberate new run (queue a fresh `WorkflowRun` row — this app has no
"reopen and continue a terminal run" mechanism, on purpose).

Invalid transitions are rejected structurally, not just by convention:

- `submit_checkpoint_decision` only succeeds when `run.status ==
  "WAITING_FOR_HUMAN"` — this is simultaneously the decision-conflict
  guard (see below) and the only door into `RESUMING`/a terminal
  checkpoint status.
- `resume_after_checkpoint` only succeeds when `run.status ==
  "RESUMING"` (or is an idempotent no-op replay against an already-
  `RUNNING` run from the *same* lease) — a runner cannot resume a run
  that's still `WAITING_FOR_HUMAN` (no decision yet) or already
  terminal.
- `_expire_stale_leases` (the existing lazy sweep) is the only path to
  `RUNNER_LOST`, and only from a lease-tracked status whose
  `lease_expires_at` has passed.

## Decision-conflict protection

There is no separate lock table and no "claim this checkpoint" step.
The same database transaction that inserts a `WorkflowCheckpointDecision`
row also flips `run.status` away from `WAITING_FOR_HUMAN`. SQLite
serializes writer commits, so whichever request's commit lands first
deterministically wins — a second, racing decision request re-checks
`run.status`, finds it already moved, and is rejected with `409`. This
is the same "first commit wins" pattern already used elsewhere in this
app (e.g. the evidence-upload storage-quota race in
`routers/evidence.py`).

Idempotency is separate from conflict protection: a request carrying an
`idempotency_key` that exactly matches an existing decision for the same
`(workflow_run_id, workflow_step_id)` returns that original row instead
of erroring — this is what makes a double-click or a browser's own
network retry safe. It is checked *before* the `WAITING_FOR_HUMAN` gate,
so a legitimate retry still succeeds even after that exact request's own
earlier, already-committed attempt moved the run on.

## The paused lease

A runner keeps calling `/heartbeat` while paused, exactly as it does
mid-execution — but `WAITING_FOR_HUMAN` and `RESUMING` renew the lease
for `PAUSED_LEASE_DURATION_SECONDS` (300s) instead of the active-
execution `LEASE_DURATION_SECONDS` (60s). The `lease_token` itself never
changes across the pause — it's the same lease from `/claim` all the way
through to `/complete`, so resuming never needs (and cannot use) a fresh
claim.

If the runner goes silent — network loss, process death, or (see below)
a Chromium crash it can still self-report — the lease lapses and the
next request to touch this project's DB (a heartbeat, a human decision
attempt, a UI poll) sweeps it to `RUNNER_LOST` via the same lazy
`_expire_stale_leases` mechanism HYB-2 already uses for the active-
execution lease. This **never touches an existing decision row**: if a
human hadn't decided yet, none exists to touch; if a PASS decision
already flipped the run to `RESUMING` and the runner then vanished
before actually reconnecting, that decision is left exactly as recorded
— the run just ends up honestly `RUNNER_LOST` instead of silently
appearing to have continued.

## Lost-runner / lost-browser scenarios

| Scenario | Detected by | Result |
|---|---|---|
| Runner loses network temporarily while paused | `waitForHumanDecision()` catches the fetch error, logs, keeps polling | No effect if it reconnects within the 300s paused-lease window |
| Runner process exits while paused | Paused lease lapses, next DB touch sweeps it | `RUNNER_LOST`, decision (if any) preserved |
| Chromium crashes while paused | Runner's own `page.isClosed()` check each poll cycle | Runner self-reports via `POST /complete` with `status: RUNNER_LOST` — honest, not silently retried as a resume |
| Lease expires (no heartbeat for 300s) | `_expire_stale_leases` | `RUNNER_LOST` |
| Server restarts while paused | N/A — all state is in SQLite | No effect; runner's next heartbeat/poll just talks to the restarted process transparently |
| User submits a decision while runner is offline | Decision endpoint doesn't require the runner to be live, only `run.status == WAITING_FOR_HUMAN` | Decision recorded normally; if the runner is not actually offline but the lease already lapsed, the run is already `RUNNER_LOST` and the decision attempt is rejected `409` |
| Runner reconnects after a decision | `/checkpoint-resume` is lease-token-gated | Only the *original* runner process (the one that actually holds the in-memory `lease_token` from its own pause loop) can resume — a fresh process has no way to obtain that token, so it cannot fabricate a continuation |
| Duplicate resume event | `run.status` already `RUNNING` when the second call arrives | Idempotent no-op reply (still lease-verified), not an error, not a re-trigger |
| Stale/mismatched decision response | `/checkpoint-resume` looks up the *latest* decision for the exact `(run_id, workflow_step_id)` and requires `resume_authorized` | `409` if it doesn't authorize resuming |
| Run cancellation while paused | `cancel_requested` flag, observed by the pause-poll loop each cycle | Runner calls `/complete` with `CANCELLED` itself, cooperative, same pattern as mid-run cancellation |

## Evidence and defects — reused, not duplicated

- Checkpoint screenshots the runner captures before pausing go through
  the *same* HYB-2 evidence-upload endpoint
  (`POST /workflow-runs/{id}/evidence`), tagged `evidence_source=RUNNER`.
- A human reviewer's own evidence (a second screenshot, an annotated
  copy, a pasted image) goes through Track A's *own*
  `POST /cycles/{cycle_id}/results/{result_id}/evidence` endpoint,
  which now optionally accepts `workflow_run_id`/`workflow_step_run_id`
  form fields (validated against the run) — defaults to
  `evidence_source=HUMAN` exactly as it always has.
- `EvidenceItem.checkpoint_decision_id` (additive, nullable) is set
  server-side when a reviewer's decision request includes
  `evidence_ids` — never client-writable directly.
- Defects reuse the existing `Defect`/`POST /defects`/`PUT
  /defects/{id}` endpoints, now accepting optional
  `workflow_run_id`/`workflow_step_run_id`/`checkpoint_decision_id`
  links.

There is no parallel "hybrid evidence" table and no parallel defect
model — this was a deliberate decision carried forward from
`HYB-1-GAP-ANALYSIS-REFRESH.md`.

## Operator / tester instructions

**As a tester reviewing a checkpoint:**
1. Open the workflow's run list (`WorkflowDetail.jsx`), expand a run
   showing `WAITING_FOR_HUMAN`.
2. The checkpoint panel shows: instructions, expected result, linked
   Track A test case(s), every prior automated step's result, the
   runner's own screenshot (and any earlier human-added evidence), and
   how long the run has been waiting.
3. Inspect the evidence; annotate it if useful (reuses the same
   annotation editor Track A's execution screen already has).
4. Optionally attach more evidence, or create/link a defect.
5. Choose PASS, FAIL, BLOCKED, or NOT_APPLICABLE, fill in the actual
   result (required for FAIL) or reason (required for BLOCKED/
   NOT_APPLICABLE), and submit.
6. PASS resumes the *same* browser session automatically — no further
   action needed. FAIL/BLOCKED end the run immediately. NOT_APPLICABLE
   ends the run and queues it for admin review.

**As an admin reviewing a NOT_APPLICABLE checkpoint decision:** the same
panel shows an Accept / Request changes action once a decision's
`review_status` is `UNREVIEWED` — identical in spirit to Track A's own
NOT_APPLICABLE review policy for `CycleTestResult`.

**As a runner operator:** nothing new to configure — a runner started
with `npm run execute` against a workflow containing a
`MANUAL_CHECKPOINT` step now pauses, waits, and resumes automatically
when a decision arrives, without any additional flags or environment
variables. `RUNNER_HEADLESS=1` still controls headed vs. headless
Chromium exactly as before.
