# Hybrid Runner Threat Model

Status: current as of HYB-5 (2026-08-02). Covers Track B only (the
hybrid Playwright runner, workflow-run job protocol, and manual
checkpoints added by HYB-0…HYB-4). See [THREAT_MODEL.md](THREAT_MODEL.md)
for Track A (manual QA) — that document is unchanged by this one.

Every claim below is backed by an automated test that exercises the
real FastAPI app (`TestClient`) with a real runner-token client, exactly
as a real Node.js runner or a real attacker would — not mocked, not
narrative-only. Test files: `backend/tests/test_hybrid_security.py`
(new, HYB-5), plus pre-existing coverage in
`backend/tests/test_workflow_runs.py` and
`backend/tests/test_workflow_checkpoints.py` (HYB-2/HYB-4).

## 1. Architecture and trust boundaries

```
React frontend (human tester/reviewer, cookie session)
   │ HTTPS, cookies, CSRF-origin-checked
   ▼
FastAPI control plane  ──────────────────────────────┐
   │ SQLite metadata (per-project file)               │
   │ EvidenceStorage (filesystem/R2)                  │
   ▼                                                   │
Outbound-only Node.js/TypeScript Playwright Runner ───┘
   (X-Runner-Token header, never a cookie/JWT)
   │ launches and controls
   ▼
A real, controlled headed Chromium browser session
   │ navigates to
   ▼
The target application under test (untrusted from the runner's POV)
```

Two structurally distinct actor types cross the FastAPI boundary:
**HUMAN** (cookie/JWT session, `get_current_user`/`require_tester`/
`require_admin`) and **RUNNER** (`X-Runner-Token` header,
`get_current_runner`) — never the same dependency, never interchangeable
(§6). A third, **SYSTEM**, is server-derived only (lease-expiry sweeps,
never client-triggered).

The runner is **outbound-only**: the backend never opens a connection
into a runner process. A runner polls/claims; it is never called into.
This means a compromised backend cannot reach into a runner's host
network — the runner always initiates.

## 2. Assets

- Runner tokens (`RunnerToken`, master DB, hashed like `RefreshToken`) —
  execution credentials, not evidence-storage credentials.
- Workflow definitions/steps (may encode `${VAR}` secret placeholders,
  never raw secrets — see §8).
- Workflow run state, step-run results, checkpoint decisions (integrity
  matters as much as confidentiality — a forged PASS is as damaging as a
  leaked screenshot).
- Evidence captured by the runner (screenshots of the target app —
  potentially sensitive, same asset class as Track A's evidence).
- The target application under test's own credentials/session (the
  runner authenticates *into* the target app on the tester's behalf).
- The human reviewer's own identity/authority (a checkpoint decision is
  a real authorization act — "resume this automation").

## 3. Runner credential theft, revocation, and replay

- **Theft**: a stolen runner token lets an attacker claim/execute jobs
  and post fabricated events for any project (see cross-project note in
  §4) until revoked. Tokens are stored hashed (`token_hash`, SHA-256),
  same discipline as `RefreshToken` — a DB leak alone does not hand out
  a working token.
- **Revocation**: `PUT /api/runner-tokens/{id}/revoke` is immediate and
  checked on every single runner-authenticated call
  (`get_current_runner` filters `revoked == False`), not just at
  claim-time. Verified:
  `test_hybrid_security.py::test_revoked_runner_token_is_rejected_everywhere`
  (revokes mid-session, confirms both `/claim` and `/heartbeat` reject
  the now-dead token — not just the endpoint that happened to trigger
  revocation).
- **Expired/garbage/missing credentials**: verified:
  `test_missing_runner_token_header_is_rejected`,
  `test_garbage_runner_token_is_rejected`.
- **Replay**: every runner-supplied event may carry an `idempotency_key`;
  `(workflow_run_id, idempotency_key)` is DB-unique, so a replayed POST
  (network retry, or an attacker capturing and resending a legitimate
  request) returns the original row, never a duplicate. Verified:
  `test_hybrid_security.py::test_replayed_event_with_same_idempotency_key_does_not_duplicate`
  and `test_workflow_runs.py`'s own idempotent-event assertion.
- **Credential leakage in logs**: the request-timing middleware
  (`main.py::request_timing_log`) logs method/path/status/duration only
  — never headers, cookies, or bodies, so `X-Runner-Token` never reaches
  a log line. No runner-token value is ever echoed back in any response
  body (mint returns it once; every other read returns only `id`/
  `label`/`status`, see `runner_tokens.py::_to_out`).
- **Credential rotation**: mint a new token, update the runner's config,
  revoke the old one once the runner process has picked up the new
  value — see
  [the runner credential-rotation guide](hybrid/RUNNER_CREDENTIAL_ROTATION.md).

## 4. Cross-project runner access (documented existing trust boundary)

`RunnerToken` lives in the master DB with **no `project_id` column** —
identical to every human `User` row, which also has no per-project
membership model. This app has never had per-project authorization for
any actor, human or runner: any authenticated ADMIN/TESTER can already
reach any project by slug, and a runner token behaves the same way.

This is a **pre-existing architectural property, not a hybrid-specific
regression** — Track A already trusted every human user across every
project slug before HYB-0 existed. HYB-5 does not silently narrow or
widen it; it makes it an explicit, tested fact:
`test_hybrid_security.py::test_runner_token_is_a_global_credential_not_project_scoped`.

**Deployment implication**: this MVP is appropriate for a single
organization's internal, trusted-user QA tooling. A genuine multi-tenant
deployment (mutually untrusting projects) would need per-project runner
scoping *and* per-project human membership as a related, larger change
— out of scope for HYB-5 and not implemented.

## 5. Job theft, duplicate execution, and lease manipulation

- **Duplicate job execution**: `POST /claim` atomically pulls the oldest
  `QUEUED` run and flips it to `CLAIMED` in the same transaction; a
  second runner racing for the same job finds the queue already empty.
  Verified: `test_hyb2_full_job_protocol` (HYB-2) and
  `test_hybrid_security.py::test_duplicate_claim_by_second_runner_is_rejected`.
- **Lease manipulation / forged lease token**: every mutating runner
  call (`heartbeat`, `events`, `step-runs`, `complete`,
  `checkpoint-resume`) requires the caller to present the exact
  `lease_token` issued at claim time, checked against
  `(run.runner_id, run.lease_token)` — a wrong token, or the *correct*
  token presented by a *different* runner's session, is rejected `409`.
  Verified:
  `test_hybrid_security.py::test_invalid_lease_ownership_is_rejected`.
- **Stale lease / lost runner**: `_expire_stale_leases` (lazy sweep, runs
  at the top of every workflow-run endpoint) marks a run `RUNNER_LOST`
  once its lease expires, so a crashed/network-partitioned runner can
  never hold a job forever, and a *different* runner cannot silently
  take over an active lease before it expires. See §11.

## 6. Actor-type forgery (human vs runner vs system)

- **A runner cannot submit a human checkpoint decision.**
  `POST /checkpoint-decision` depends on `require_tester` (real
  cookie/JWT session) — an `X-Runner-Token`-only caller has no such
  session and is rejected `401` before the route body ever runs.
  Verified:
  `test_hybrid_security.py::test_runner_cannot_submit_a_human_checkpoint_decision`.
- **A human session cannot submit runner events.** `POST /events`
  depends on `get_current_runner` (`X-Runner-Token` required) — a
  logged-in human's cookie session carries no such header and is
  rejected `401`. Verified:
  `test_hybrid_security.py::test_human_session_cannot_submit_runner_events`.
- **Forged human identity.** `decided_by_user_id`/`decided_by_email` on
  `WorkflowCheckpointDecision` are always taken from the authenticated
  session server-side (`user.id`/`user.email` in
  `workflow_runs.py::submit_checkpoint_decision`) — the request schema
  doesn't even accept client-supplied identity fields, and any extra
  fields in the body are ignored. Verified:
  `test_hybrid_security.py::test_decided_by_identity_is_server_derived_never_client_supplied`.
- **Fake PASS events / invalid state transitions.** A checkpoint can
  only be decided while the run is `WAITING_FOR_HUMAN`; a decision
  attempt against any other status is rejected `409`
  (`test_checkpoint_decision_on_non_waiting_run_is_rejected`), and a
  resume attempt against a run that was never `RESUMING` is rejected
  `409` (`test_checkpoint_resume_without_waiting_state_is_rejected`).
  There is no code path that flips a run to `RUNNING`/`PASSED` without
  either a real automated step-run completing or a real, lease-verified
  `checkpoint-resume` following an actual `resume_authorized` decision.
- **Human FAIL is genuinely terminal.** The same DB transaction that
  inserts a `FAIL` decision row also flips `run.status` away from
  `WAITING_FOR_HUMAN` — a racing second decision (another tester, or a
  compromised/buggy runner attempting to "fix" the outcome) finds the
  run already moved on and gets `409`, never a silent overwrite; and the
  runner's own `checkpoint-resume` call is rejected `409` once the run
  is `FAILED`, since only a decision with `resume_authorized=True`
  (i.e. `PASS`) can ever move a run back to `RESUMING`. Verified:
  `test_hybrid_security.py::test_human_fail_cannot_be_overridden_by_later_automation_or_racing_decision`
  and the equivalent real headed-Chromium scenario in HYB-4's own
  session verification (see `docs/hybrid/HYB-4-CHECKPOINTS.md`).
- **Unauthorized checkpoint review.** Reviewing a `NOT_APPLICABLE`
  decision (`POST /checkpoint-decisions/{id}/review`) requires
  `require_admin` — a TESTER session is rejected `403` by the same
  `require_roles` mechanism proven generically in
  `test_security_boundaries.py::test_tester_cannot_admin_only_actions`.

## 7. Locator manipulation and malicious target pages

- Locators are structured (`locator_strategy` + `locator_value` +
  `locator_fallbacks_json`), never raw injected source/selector code
  executed as-is, and never raw pixel coordinates used for replay
  (`RecordedStep.diagnostic_x/y` are explicitly diagnostic-only, never
  resolved against during replay — see `models.py`'s own comment on
  those columns).
- **Arbitrary JavaScript execution risk**: the workflow step vocabulary
  (`WORKFLOW_STEP_TYPES`) has no "run arbitrary script" step type. A
  workflow author cannot inject arbitrary JS to execute inside the
  runner's Playwright context through the step model itself.
- **Malicious target pages**: the runner navigates only to
  `target_base_url`/step-defined URLs an authenticated tester configured
  for that cycle/workflow — it does not follow attacker-supplied
  redirects into new destinations beyond what Playwright's normal
  navigation does, and every navigation is logged as a `STEP_STARTED`/
  `STEP_COMPLETED`/`STEP_FAILED` event with the resulting `url`/`title`
  captured in checkpoint payloads, giving a human reviewer visibility
  into where the browser actually went.
- **Recorder keylogging risk**: `HYB-3-*` recording only runs inside a
  Playwright browser *the runner itself launched* for that recording
  session — never a tester's everyday browser, never a global OS input
  hook — and `RecordedStep.input_value` is explicitly never populated
  for `is_sensitive` fields (see `models.py`'s own comment on that
  column and §8 below).
- **SSRF-style risk**: the runner is a Node.js process with outbound
  network access equivalent to any browser automation tool — it is not
  given elevated network placement (no access to internal-only backend
  network segments beyond what an ordinary browser on that host would
  have). Operators should run runner hosts with the same network
  segmentation discipline as any other browser-automation worker;
  this app does not add or remove that boundary.

## 8. Secret-variable handling (password/OTP/token capture)

A workflow step marked `is_sensitive=True` must have an `input_value`
that is exactly a `${VAR_NAME}` placeholder — the router rejects any
value that doesn't match that pattern at creation/update time
(`workflows.py::_validate_step`). The **real secret value never enters
this application's database, logs, events, reports, Excel export, or
ZIP export at all** — it is resolved only inside the runner process's
own local environment (`runner/.env`, gitignored, never committed) at
execution time, and the resolved value is used to fill the target
page's field directly via Playwright without ever being sent back to
the FastAPI backend in any request body, event payload, or step-run
outcome. Verified:
`test_hybrid_security.py::test_sensitive_step_rejects_a_raw_secret_value`.

Consequence for every downstream hybrid feature added in HYB-5: since no
raw secret is ever stored, none can leak through the new timing
endpoints, hybrid dashboard/reports, Excel sheets, or ZIP manifest —
there is nothing sensitive in those tables to leak in the first place.

## 9. Evidence upload abuse and export leakage

- Runner-uploaded evidence reuses the exact same `EvidenceItem` table,
  quota check, content-type sniffing (never trusts the client's claimed
  MIME type), and size cap as Track A's own tester-driven upload path —
  no parallel, less-scrutinized upload surface exists for the runner.
- Evidence bytes are only ever read through the authorized
  `EvidenceStorage` abstraction (filesystem or R2) — HYB-5's ZIP export
  now additionally **verifies every included file's SHA-256 against its
  recorded `original_sha256` before packaging it**; a mismatch (storage
  corruption or tampering) is treated as `missing` rather than silently
  including bad bytes. Verified:
  `test_hybrid_excel_zip_export.py::test_hybrid_zip_manifest_links_every_entity_and_verifies_checksums`.
- **Malicious export filenames / ZIP path traversal**: evidence archive
  paths are built from `_safe_slug()`-sanitized components (alphanumeric
  + `_`/`-` only), confining every entry under `evidence/...` regardless
  of what a `checkpoint_code` or filename contains. Verified:
  `test_hybrid_security.py::test_zip_export_sanitizes_malicious_checkpoint_code_in_filename`.
- Presigned URLs are never substituted into an export — every ZIP
  contains the real bytes, read server-side (existing Track A
  requirement, unchanged and re-verified for hybrid evidence in the same
  test above).

## 10. Event tampering and denial of service

- Every `RunnerExecutionEvent`/`WorkflowCheckpointDecision` row is
  append-only — no endpoint updates or deletes a past event or decision
  (§6's FAIL-terminal guarantee is a direct consequence).
- **Heartbeat/event flood (DoS)**: HYB-5 adds rate limits to the two
  highest-frequency runner endpoints — `POST /heartbeat` (120/minute)
  and `POST /events` (300/minute), using the same `slowapi` limiter
  already protecting `/api/auth/login`. A single misbehaving or
  malicious runner process cannot flood a project's event log or lease
  system beyond that bound. (`/claim` is naturally self-limiting: an
  empty queue returns immediately and costs one indexed query.)

## 11. Stale runner and lost-run recovery (honest failure, no fabrication)

See [the recovery runbook](hybrid/RECOVERY_RUNBOOK.md) for the full
operator-facing procedure. The security-relevant guarantee: recovery
**never fabricates a successful continuation or reuses a dead browser
session**. A lease-expiry sweep only ever moves a run to the honest
terminal state `RUNNER_LOST`; there is no code path where the backend
invents step results on a runner's behalf, and `checkpoint-resume`
always re-validates the lease and the specific decision before allowing
any run to continue — a fresh runner process with no knowledge of the
original `lease_token` can never resume a paused run and pretend it's
the same browser session.

## 12. CORS/CSRF boundary for hybrid endpoints

The existing CSRF-origin check (`main.py::csrf_origin_check`) applies to
every cookie-authenticated `POST`/`PUT`/`PATCH`/`DELETE`, including the
hybrid workflow-run endpoints (`POST /workflow-runs`, checkpoint
decisions, etc.) — it is middleware, not a per-router opt-in, so hybrid
routes inherit it automatically. Verified:
`test_hybrid_security.py::test_hybrid_endpoint_cookie_write_without_origin_is_rejected`.
Runner-token requests carry no cookie, so this check does not (and need
not) apply to them — a runner is never subject to the browser-cookie
CSRF threat model in the first place (§1).

## 13. Known limitations (explicit, not silently accepted)

- No per-project runner/user authorization boundary (§4) — acceptable
  for a single-organization internal deployment only.
- No mutual TLS / client-certificate pinning for runner connections —
  relies on the bearer-style `X-Runner-Token` over HTTPS, the same trust
  level as every other credential in this app.
- The recorder/runner's own host-level security (OS hardening, endpoint
  protection) is outside this application's control surface — this
  threat model covers the application boundary, not the runner host's
  OS security.
- Rate limiting on runner endpoints (§10) is per-remote-address; a
  distributed flood from many source IPs is not mitigated by this alone
  (matches the existing limitation already accepted for `/api/auth/login`
  in `THREAT_MODEL.md`).
