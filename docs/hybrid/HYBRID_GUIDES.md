# Hybrid Guides (HYB-5)

Consolidated into one document rather than six near-duplicate files —
a deliberate scope decision (documented here rather than silently made)
given the size of everything else HYB-5 already covers. Each section
below is a complete, standalone guide for its named role.

## Architecture overview

```
React frontend (tester/reviewer, cookie session)
        │
        ▼
FastAPI control plane
        │
        ├── SQLite metadata (per-project file — the project boundary
        │   IS the file, same as Track A)
        │
        ▼
EvidenceStorage (filesystem local-dev default, Cloudflare R2 in prod)
        │
        ▼  (outbound-only — the backend never calls into a runner)
Node.js/TypeScript Playwright Runner (X-Runner-Token, never a cookie)
        │
        ▼
A real, controlled headed Chromium browser session
        │
        ├── workflow recording (HYB-3)   — buffers RecordedStep drafts
        ├── job execution (HYB-2)        — claim → step-runs → complete
        ├── manual checkpoint (HYB-4)    — pause, real human decision, resume
        └── evidence + annotation        — reuses Track A's EvidenceItem
        │
        ▼
Reports and exports (HYB-5)
        — hybrid dashboard/reports, Excel (7 Track A + 8 hybrid sheets),
          ZIP (real evidence bytes + a manifest linking every hybrid
          entity by id)
```

Nothing here replaces manual execution — hybrid is additive. A
workflow run's steps are logged as structured `WorkflowStepRun` rows
(machine) and `WorkflowCheckpointDecision` rows (human), always kept in
disjoint sets so provenance is never ambiguous (see
[HYBRID_RUNNER_THREAT_MODEL.md](../HYBRID_RUNNER_THREAT_MODEL.md) §6).

## Workflow-author guide

1. `POST /api/{slug}/workflows` — create a `WorkflowDefinition` (a
   stable name/identity across revisions, mirroring `TestSuite`).
2. `POST .../revisions` — create a `DRAFT` revision. Steps are only
   editable while `DRAFT`.
3. Add steps in order (`POST .../revisions/{id}/steps`): pick a
   `step_type` from `NAVIGATE`/`CLICK`/`FILL`/`SELECT`/`CHECK`/
   `UNCHECK`/`PRESS_KEY`/`WAIT_FOR_ELEMENT`/`ASSERT_VISIBLE`/
   `ASSERT_TEXT`/`ASSERT_URL`/`SCREENSHOT`/`MANUAL_CHECKPOINT`. A
   structured locator (`locator_strategy` + `locator_value` +
   optional `locator_fallbacks_json`) is required for interaction
   steps — never raw source/selector code.
4. **Sensitive fields**: set `is_sensitive: true` and give
   `input_value` a `${VAR_NAME}` placeholder — never a literal
   password/token. The runner resolves the real value from its own
   local environment at execution time; the real secret never reaches
   this application (see threat model §8).
5. `MANUAL_CHECKPOINT` steps need `checkpoint_instructions` (what a
   human reviewer should check) and optionally an `expected_value` and
   `evidence_policy`.
6. Optionally link Track A test cases (`WorkflowTestCaseLink`) so a
   checkpoint reviewer sees the exact case snapshot alongside the
   automation.
7. `POST .../revisions/{id}/publish` (ADMIN) — makes the revision
   immutable and runnable. A correction after publish is always a
   `clone` into a new `DRAFT`, never an in-place edit.

## Recorder guide

The browser recorder (HYB-3) captures candidate steps by watching a
real Playwright browser the runner itself launches for that session —
never your own everyday browser, never a global OS input hook.

1. `POST /api/{slug}/recording-sessions` against a `target_url`.
2. A runner claims it (`RECORDING_SESSION_STATUSES`: `REQUESTED` →
   `CLAIMED` → `RECORDING`), opening a real headed Chromium window.
3. Interact with the target page normally; each action becomes a
   `RecordedStep` draft (never auto-saved as a real `WorkflowStep`).
   Fields marked sensitive (e.g. a password field) never have
   `input_value` populated — you must manually set the `${VAR}`
   placeholder after the fact.
4. Use "test this locator" on any uncertain step (`needs_review`/
   `review_note` flags) — the runner re-resolves it live with the same
   `resolveLocator()` replay itself uses, while the recording browser
   is still open, and posts the result back.
5. "Save as draft" converts the reviewed `RecordedStep` buffer into
   real `WorkflowStep` rows on a `DRAFT` revision (reusing HYB-1's own
   step-creation code) — indistinguishable from hand-built steps once
   saved. Stopping without saving discards the buffer entirely.

## Tester guide

Hybrid runs are queued exactly like starting an automated check against
a Track A cycle result:

1. `POST /api/{slug}/workflow-runs` with a `workflow_revision_id`
   (must be `PUBLISHED`) and, to flow results/evidence into Track A,
   a `cycle_test_result_id`.
2. Watch progress via `GET /api/{slug}/workflow-runs/{id}` — status,
   per-step results, event history. The frontend's Workflow Detail page
   polls this for you.
3. If a `MANUAL_CHECKPOINT` is reached, the run enters
   `WAITING_FOR_HUMAN` — see "Checkpoint-reviewer guide" below.
4. A terminal run (`PASSED`/`FAILED`/`BLOCKED`/`NOT_APPLICABLE`/
   `CANCELLED`/`RUNNER_LOST`) flows its evidence and (if linked) its
   checkpoint decisions into the same Track A cycle result reporting/
   export pipeline you already use — see the reporting/export guide.

## Checkpoint-reviewer guide

1. `GET /api/{slug}/workflow-runs/{id}/checkpoint?workflow_step_id=...`
   — one call returns everything: instructions, expected value, linked
   Track A case(s) at their exact revision snapshot, prior automated
   step results, the runner's own uploaded screenshot, decision
   history, and elapsed waiting time.
2. Review the automated steps' actual behavior and the runner's
   screenshot; annotate it if useful (reuses the same annotation editor
   Track A evidence already has).
3. `POST .../checkpoint-decision` with `status` = `PASS`/`FAIL`/
   `BLOCKED`/`NOT_APPLICABLE`:
   - `PASS` authorizes the *same* runner process, *same* browser
     session, to resume — it is never re-launched fresh.
   - `FAIL` requires `actual_result_md` and is **terminal**: no later
     automation or racing decision can override it (see threat model
     §6).
   - `BLOCKED`/`NOT_APPLICABLE` require a `reason`; `NOT_APPLICABLE`
     enters the same admin-review queue as Track A's own policy.
4. A racing second decision on the same checkpoint gets `409` — the
   first commit wins, never a silent overwrite.

## Runner installation guide

1. Prerequisites: Node.js (matching `runner/package.json`'s engines),
   `npm install` inside `runner/`, then `npx playwright install
   chromium` (downloads a real headed-capable Chromium build).
2. An ADMIN mints a runner token: `POST /api/runner-tokens`
   (`{"label": "..."}`) — the raw token is shown **once**.
3. Create `runner/.env` (gitignored — never commit it):
   ```
   BACKEND_BASE_URL=https://your-backend-host
   PROJECT_SLUG=your-project-slug
   RUNNER_TOKEN=<the token from step 2>
   TARGET_BASE_URL=https://the-app-under-test
   TARGET_EMAIL=...
   TARGET_PASSWORD=...
   ```
4. `npm run execute` (job execution) or the recorder entry point for
   recording sessions — see `runner/src/main.ts`/`executeMain.ts`.

## Runner operator guide

- **Day-to-day**: `GET /api/runner-tokens` shows `ONLINE`/`STALE`/
  `OFFLINE`/`REVOKED` per token (any authenticated call counts as a
  heartbeat).
- **Stuck jobs / lost runners / cancellation**: see
  [RECOVERY_RUNBOOK.md](RECOVERY_RUNBOOK.md) — covers every failure
  mode (stale lease, runner lost before/during/while-paused, Chromium
  crash, server restart, stuck QUEUED/CLAIMED/WAITING_FOR_HUMAN,
  cancellation, safe retry vs. deliberate rerun, evidence
  reconciliation, orphaned storage objects).
- **Credential rotation / revocation**: see
  [RUNNER_CREDENTIAL_ROTATION.md](RUNNER_CREDENTIAL_ROTATION.md).
- **Security model**: see
  [HYBRID_RUNNER_THREAT_MODEL.md](../HYBRID_RUNNER_THREAT_MODEL.md)
  before deploying a runner outside a single trusted organization's
  network (§4's cross-project trust boundary matters here).

## Hybrid reporting/export guide

- `GET /api/{slug}/hybrid-reports/dashboard` — run-status counts,
  machine-vs-human provenance (kept structurally distinct), runner
  reliability, retry/runner-lost frequency, checkpoint-waiting summary,
  evidence completeness, defect linkage, recent activity.
- `GET .../locator-failures`, `.../failure-categories`,
  `.../workflows-frequent-failures`, `.../slowest-steps`,
  `.../runner-reliability` — each states its own denominator (see
  `backend/app/hybrid_metrics.py` docstrings).
- `GET .../timing/runs/{id}` — full per-run timing breakdown (queue
  delay, browser startup, per-step durations/retries, checkpoint
  waiting/resume delay, evidence-upload duration).
- `GET .../timing/run-trend` / `.../timing/step-trend` — historical
  trend across every run of a workflow, oldest first. Never overwrites
  a past run's own numbers.
- Excel export (`GET /cycles/{id}/export/excel`): the original 7 Track A
  sheets are unchanged; 8 new hybrid sheets are appended (Workflow
  Definitions/Revisions/Steps/Runs, Step Results, Checkpoint Decisions,
  Runner Activity, Timing Trends), scoped to the same cycle.
- ZIP export (`GET /cycles/{id}/export/zip`): `manifest.json`'s new
  `hybrid` key links every hybrid entity by id with its own timestamps/
  durations; every evidence entry (Track A and hybrid alike) is
  checksum-verified before being written into the archive.

## Known limitations

- No stable logical-step key across workflow revisions yet — step
  duration trends match by exact description within a workflow; a
  renamed step starts a new trend line.
- No per-project runner/user authorization boundary (see threat model
  §4) — appropriate for a single trusted organization, not a genuine
  multi-tenant deployment.
- A literal headed-Chromium run of a 50+-step workflow and a from-
  scratch clean-environment rehearsal were not performed in the HYB-5
  session that wrote this document — see
  [HYB5_VERIFICATION_SCOPE.md](HYB5_VERIFICATION_SCOPE.md) for the exact
  scope and the recommended next step.
- Release Closure's three human-operated checks (real R2 staging smoke
  test, human-operated Screen Capture acceptance, human-operated
  clipboard-paste acceptance) remain unresolved — the project remains
  **NOT PRODUCTION READY** regardless of hybrid feature completeness.
