# Roadmap

This roadmap now has two tracks, per
`QA_AGAIN_HYBRID_AI_QA_MVP_EXPANSION.md` section 15:

- **Track A** (Phases 0–7 below): the manual, evidence-first QA rebuild
  per `QA_AGAIN_REBUILD_PROMPT_FASTAPI_REACT.md` section 9. This remains
  the baseline — Track B is additive, not a replacement.
- **Track B** (HYB-0…HYB-5, formerly "Phase 8"): the approved hybrid
  manual+automation expansion. See
  [ADR-HYB-001](adr/ADR-HYB-001-playwright-hybrid-execution.md) for the
  one specification change this required (superseding the "no Playwright
  automation platform" non-goal — nothing else about Track A changed).

0. Repository audit + ADR-0001 (evidence storage, roles, export — done).
1. Backend/frontend scaffold matching PM-Again's shape, health check +
   login working end-to-end.
2. Identity/projects/roles.
3. Test suites, immutable revisions, Excel/CSV import (strict header
   validation) — **done** (suites, DRAFT/PUBLISHED/SUPERSEDED revisions,
   clone-for-correction, publish-supersedes-prior, strict-header Excel/CSV
   import+export, verified end-to-end via Playwright screenshots).
   **Not yet done**: the Markdown (`.md`) importer for the SATL-style
   source document (rebuild prompt section 11) — deferred because the
   required fixture file
   (`SATL_REGRESSION_CHECKPOINT_SCRIPT_PRE_GOLIVE_2026AUG01.md`) isn't in
   this workspace yet and the spec explicitly says "do not invent missing
   source content." Revisit once that fixture is available; until then,
   manual entry + Excel/CSV import cover suite/revision/case creation.
   **This is a separate deferred item, not a Release Closure blocker** —
   it is not part of `docs/RELEASE_CHECKLIST.md`'s blocking-items list
   and does not gate a production-readiness decision unless someone
   explicitly promotes it into release scope later.
4. Test cycles and execution — **done**. `TestCycle` (snapshots one exact
   PUBLISHED revision's cases as `NOT_RUN` results at creation; a later
   publish never touches an existing cycle), `CycleTestResult`
   (PASS/FAIL/BLOCKED/NOT_APPLICABLE with FAIL/BLOCKED/N-A validation,
   N-A admin review/approval), `CycleResultHistory` (append-only, one row
   per mutation, `result_revision_no` increments, never overwritten).
   Cycle lifecycle DRAFT|READY|IN_PROGRESS|REVIEW|COMPLETED|LOCKED|
   CANCELLED; locking blocks all result mutation, admin-only reopen
   requires a reason and is audit-logged. Evidence-first execution UI
   (case list + filters, detail panel, actual-result editor, sticky
   PASS/NG/BLOCKED/N-A actions, unsaved/saving/saved/error states,
   per-result draft isolation, history panel). Verified end-to-end via
   curl (full lifecycle incl. lock/reopen/validation rejections) and
   Playwright screenshots of the actual execution UI.

   Hybrid extension points included per HYB-0's findings, not enabled:
   `execution_mode` (MANUAL|AUTOMATED|HYBRID, default MANUAL),
   `result_source` (HUMAN|RUNNER|SYSTEM, default HUMAN) on both
   `CycleTestResult` and `CycleResultHistory` (as `change_source`), and a
   reserved nullable `runner_run_id` (unused until HYB-2's real runner
   registration exists). `step_kind`/`checkpoint_status`/
   `evidence_source` were deliberately **not** added — they only mean
   something once `workflow_steps` (HYB-1) exists; adding them now would
   be meaningless nullable columns, not a real hook.

   **Historical Phase 4 gap — resolved in Phase 5.** The rebuild prompt
   requires blocking PASS when the project/cycle evidence policy
   requires evidence and none exists; at the time Phase 4 shipped there
   was no evidence model yet to enforce it against. Kept here only for
   traceability — `TestCycle.require_evidence_for_pass` now actually
   enforces this (see Phase 5 below); do not read this paragraph as
   describing current behavior.
5. Evidence capture/annotation/storage — **done**, storage backend
   **updated 2026-08-01 per [ADR-0002](ADR-0002-evidence-storage-r2.md)**:
   evidence binaries now live in a private Cloudflare R2 bucket (Standard
   storage class) behind a swappable `EvidenceStorage` abstraction
   (`backend/app/storage/`) — filesystem remains the zero-config local
   dev default, R2 is what production uses. All metadata (checksums,
   sizes, MIME types, actor provenance, archive state) stays in the
   project SQLite DB regardless of which storage backend is active; only
   binary payloads move. Non-guessable UUID-based object keys, upload is
   content-addressed/idempotent (a retried identical upload returns the
   existing row instead of duplicating it), and a DB-write failure after
   a successful storage write triggers a compensating delete (logged
   loudly if that itself fails — see
   [EVIDENCE_STORAGE_LIFECYCLE.md](EVIDENCE_STORAGE_LIFECYCLE.md) for
   reconciliation). Per-project storage quota
   (`GET`/`PUT /api/projects/{slug}/storage-quota`, configurable
   70/85/95/100% thresholds, blocks upload past 100%) is now built —
   this closes the gap this section used to list as "not built." Deploy
   details and required env vars in
   [DEPLOYMENT.md](DEPLOYMENT.md). Verified via 11 automated pytest
   tests (idempotency, quota enforcement, archive/quota interaction,
   compensating cleanup on a simulated DB failure, and the R2 backend
   itself against a local mock S3 server) plus a full curl re-verification
   of the upload/download/PASS-gate flow after the refactor — a real bug
   (a doubled `evidence/evidence/...` path segment) was caught and fixed
   before the automated tests even ran, during test-fixture setup.
   `EvidenceItem.object_key` replaced the earlier `original_path` field
   name once it stopped being literally a filesystem path.

   `EvidenceItem` (immutable original, `{sha256}.{ext}`-independent
   UUID-based key naming so the client-supplied filename never touches a
   storage key, MIME-signature sniffing that rejects a mismatched/spoofed
   content-type, 8MB size cap) + `EvidenceRevision`
   (append-only annotation history, design-state JSON not a rendered
   image per revision, matching the spec's own "unless proven necessary"
   guidance). Three capture paths funnel into the same authenticated
   upload endpoint: file upload, clipboard paste, and the Screen Capture
   API. A custom lightweight HTML5 Canvas annotator (arrow, rectangle,
   highlight, freehand, text, numbered callout, blur/redaction, orange
   default, undo/redo) — **decision**: built instead of react-konva/
   Filerobot (the rebuild doc asked to re-run that compatibility spike;
   a dependency-free canvas tool sidesteps the React-19-compatibility
   question entirely). **Closes the Phase 4 gap**: `TestCycle.
   require_evidence_for_pass` (default true) now actually blocks PASS
   with no active evidence attached, enforced in
   `cycle_results.py::update_result`. Upload/annotate/archive all reuse
   the same LOCKED-cycle guard as results; reopening re-enables them.
   Every evidence/annotation row carries a real `captured_by`/
   `created_by` and server timestamp. `EvidenceItem.evidence_source`
   (`HUMAN|RUNNER|SYSTEM`, default `HUMAN`) is the hybrid extension
   point, unused. Verified via a full curl lifecycle (sniff rejects a
   spoofed non-image file, PASS blocked then allowed, lock/reopen,
   archive) and a Playwright run through the real UI including drawing
   and saving real arrow/rectangle annotation shapes (confirmed via the
   stored `annotation_json`, not just a UI screenshot).

   **Documented gaps, not silently dropped**:
   - Screen Capture API and clipboard-paste upload paths are
     implemented for real use but not exercised by the Playwright
     verification — `getDisplayMedia` needs a user gesture + OS picker
     that isn't automatable headless, and paste requires a synthetic
     `ClipboardEvent` with real image bytes. Both share the exact same
     upload code path as the file-input flow, which *was* verified, so
     the marginal risk is in the two browser-API call sites themselves,
     not the upload/storage logic.
   - No thumbnails or stored image width/height — deliberately no
     Pillow/image-processing dependency added for Phase 5; the original
     master spec listed these as optional MVP fields.
6. Dashboard, reports, Excel/ZIP export — **done**, 2026-08-01. Before
   this phase, four retrofits to Phase 5's R2 evidence storage were
   carried forward per explicit user requirement (all pytest-verified):
   presigned downloads now override Content-Disposition/Content-Type so
   a browser save-as shows the evidence's real filename, not its opaque
   object key; a concurrent-upload quota race is closed (post-commit
   re-check + deterministic self-evict — SQLite serializes commits, so
   whichever request commits last detects and undoes an over-quota
   race, never both); `EvidenceStorage.list_keys()` + a safe, idempotent
   `app/reconciliation.py` (re-verifies "not referenced by a committed
   row" immediately before every delete, dry-run by default) plus an ops
   CLI (`scripts/reconcile_evidence.py`); and a real (uncommitted-secrets)
   R2 staging smoke test (`scripts/r2_staging_smoke_test.py`) — **written
   but not run in this environment**, no real Cloudflare credentials are
   available here; must be run by whoever holds the staging R2
   credentials before production release (see `docs/DEPLOYMENT.md`).

   Added `Defect` and `SignOff` (minimal — original domain model
   entities the spec required but no earlier phase built) so dashboard's
   "open defects by severity" and Excel's `03_NG_Defects`/`06_Sign_Off`
   sheets have real data instead of being faked or left empty.

   Dashboard: total/PASS/FAIL/BLOCKED/NOT_RUN/N-A counts, pass rate,
   evidence completeness, go-live readiness (with a blocker list),
   open defects by severity, pending N/A reviews, storage usage, recent
   activity — for the project's "active cycle" (most recently created
   non-CANCELLED cycle; spec doesn't define "active", documented choice).
   **Formulas the spec left genuinely undefined, resolved and
   documented** (surfaced explicitly, not silently chosen):
   pass rate = `PASS / (total − approved NOT_APPLICABLE)`, NOT_RUN stays
   in the denominator so an incomplete cycle can't show a misleadingly
   high rate; evidence completeness = `executed results with >=1 ACTIVE
   evidence / executed results`; go-live readiness = no P0 case
   FAIL/BLOCKED/NOT_RUN, no P0 N/A case unapproved, no open P0/P1 defect
   linked to the cycle.

   All 10 named reports (§16) exist as real backend endpoints
   (`/api/{slug}/reports/*`); the frontend consolidates them into **one**
   Reports page with a report-type selector rather than 10 near-duplicate
   screens — a deliberate scope call (the Excel export already surfaces
   the same data structurally), not a silent cut.

   Excel export: exact 7 sheets/columns from §17 (`00_Cover` …
   `06_Sign_Off`), no embedded thumbnails (same no-Pillow decision as
   Phase 5 — evidence referenced by ID/hash/caption, full images live in
   the ZIP). ZIP export: server-side, in-memory (`io.BytesIO`, no temp
   files to clean up), every evidence file read via
   `EvidenceStorage.get()` — **never** a presigned URL substituted into
   the archive, per explicit requirement. A missing storage object is
   recorded in `manifest.json` as `"missing": true` and skipped, not a
   hard failure of the whole export. Archived evidence is **included**
   in exports (marked `"status": "ARCHIVED"`) and still counts toward
   storage quota — exports are historical records, archiving only hides
   from the live execution UI, it doesn't delete.

   Verified: 20 automated pytest tests (dashboard formulas, Excel sheet
   names/columns/rows via openpyxl, ZIP extraction with manifest-to-file
   sha256 consistency, archived-evidence inclusion, missing-object
   graceful handling, concurrent-upload quota race, reconciliation
   safety) plus a full Playwright run through the real UI — dashboard
   tiles, the Reports page across multiple report types, and **actual
   file downloads** (not just HTTP 200s) of both the Excel workbook and
   ZIP package, both opened/inspected afterward to confirm they're real,
   non-corrupt files.
7. Hardening, threat model, capacity doc, user guides, handover —
   **code and documentation complete, 2026-08-01; production-readiness
   is NOT yet declared** — see `docs/RELEASE_CHECKLIST.md` for the three
   explicit release blockers (real R2 staging smoke test, Screen Capture
   API real-browser evidence, clipboard-paste real-browser evidence, all
   unexecuted in this development environment).

   Two real bugs found and fixed while writing this phase's security
   tests, not just theoretical review: (1) a CSRF gap — cookies are
   `SameSite=None` in production, and the evidence-upload endpoint's
   `multipart/form-data` content type doesn't require a CORS preflight,
   so a forged cross-site upload could ride a victim's session; closed
   with `main.py::csrf_origin_check`, an Origin-header check on every
   cookie-authenticated write (Bearer-authenticated requests are exempt —
   a browser never auto-attaches those to a forged request). (2) openpyxl
   throws `IllegalCharacterError` and aborts an **entire** export if any
   field contains an XML-illegal control character (e.g. a stray NUL
   byte pasted into an actual-result field) — one bad row could crash
   every export for a cycle; fixed with `report_excel.py::_clean_cell`
   stripping illegal characters before every cell write. Also hardened:
   filename sanitization left `..` sequences intact (dots were in the
   allowed charset) — cosmetic today (never used to build a storage
   path), tightened anyway since it's user-visible metadata.

   New docs: `THREAT_MODEL.md` (fresh, grounded in the actual FastAPI/
   SQLite/Pages/Fly/R2 architecture), `BACKUP_RESTORE.md` (+ a real,
   tested `scripts/backup_databases.py` using SQLite's online backup API
   for consistency), `CAPACITY.md`, `RELEASE_CHECKLIST.md`,
   `RELEASE_REHEARSAL.md`, `HANDOVER.md`, `guides/{ADMIN,TESTER,
   VIEWER}_GUIDE.md`. Extended: `DEPLOYMENT.md` (environments table,
   rollback procedure, secrets rotation), `EVIDENCE_STORAGE_LIFECYCLE.md`
   (R2 credential rotation, quota recovery, inaccessible-object recovery).

   Verified: 41 automated pytest tests (20 carried from Phases 5–6 + 21
   new — role/auth/CSRF/CORS/rate-limit boundaries, evidence abuse cases,
   export security), all passing cold in a freshly created venv. A full
   clean-environment release rehearsal (fresh venv, fresh
   node_modules, fresh data dir, real headed-browser Playwright run
   through login → suite → publish → cycle → execute → evidence → PASS →
   dashboard → real Excel/ZIP downloads, both files opened and verified
   afterward) — recorded in `docs/RELEASE_REHEARSAL.md`.

## Performance Fast Pass — 2026-08-02

A measurement-first performance pass on Track A (not a new phase, no
feature work) — see [PERFORMANCE_FAST_PASS.md](PERFORMANCE_FAST_PASS.md)
for the full before/after data. Fixed a real payload bloat bug (the
cycle-results list endpoint was shipping every case's full markdown on
every row — 354KB → 162KB for a 200-case cycle), an N+1 in the cycle
list endpoint, redundant dashboard/report metric recomputation, added
additive SQLite indexes on hot foreign-key columns, and made Cycle
Execution fetch case detail lazily per selection with a session cache.
Does not change release status or touch the three release blockers.

## Release Closure — Track A

Status: **BLOCKED — Track A implementation is complete, but production
readiness has not been declared.**

Exact procedure: [RELEASE_CLOSURE.md](RELEASE_CLOSURE.md). Required
closure steps:

- Run the real Cloudflare R2 staging smoke test.
- Verify the Screen Capture API in a real browser with a human operator.
- Verify clipboard-image paste in a real browser with a human operator.
- Record the real environment, operator, date, outcome, and evidence
  references in [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md) and
  [RELEASE_REHEARSAL.md](RELEASE_REHEARSAL.md).
- Re-run the complete backend pytest suite.
- Re-run the frontend production build.
- Report either `PRODUCTION READY` or `NOT PRODUCTION READY`.
- Create a stable Track A baseline tag before HYB-1 begins.

### Intended delivery sequence

```
Track A implementation complete
  → Release Closure
  → Production-readiness decision
  → Stable Track A baseline tag
  → Refreshed hybrid gap analysis
  → HYB-1
  → HYB-2
  → HYB-3
  → HYB-4
  → HYB-5
```

HYB-1 does not start until this sequence reaches it — that includes not
starting HYB-1 merely because Track A's code is complete; Release
Closure, the production-readiness decision, the baseline tag, and the
refreshed gap analysis all come first.

**Progress against this sequence, 2026-08-02**: the `track-a-baseline`
git tag has been created (code-complete marker, not a readiness claim)
and the hybrid gap analysis has been refreshed —
[HYB-1-GAP-ANALYSIS-REFRESH.md](hybrid/HYB-1-GAP-ANALYSIS-REFRESH.md).
**Release Closure and the production-readiness decision are still
outstanding** — the three human-operated checks in
[RELEASE_CLOSURE.md](RELEASE_CLOSURE.md) have not been run.

**Update, 2026-08-02, later same day**: the user explicitly superseded
the "HYB-1 does not start until Release Closure" rule above for this
delivery, reclassifying Release Closure's three checks as *release*
blockers only, not *development* blockers — HYB-1 work is authorized to
proceed on a dedicated `feature/hybrid-mvp` branch while Release Closure
remains open. Production readiness is **not** claimed regardless of how
much HYB work completes; see Track B below for HYB-1's actual status.

## Track B — Hybrid manual+automation expansion (HYB-0–HYB-4 complete; HYB-5 pending)

Full detail lives in `QA_AGAIN_HYBRID_AI_QA_MVP_EXPANSION.md`; this is
the index. QA-Again gains a separate **QA Runner** (Node.js + Playwright,
outbound-only communication to the FastAPI control plane — never
Playwright embedded in the public API process) that can execute
repeatable browser steps and pause at manual checkpoints for a human
tester to verify, capture evidence, and decide PASS/FAIL/BLOCKED/N/A.
Machine assertions and human decisions are always recorded with distinct
provenance; AI may draft content but never finalizes a result.

Per the hybrid doc's section 20 ("first instruction for the
implementation team"), before any feature build:

1. Gap analysis against the hybrid doc's sections 4–13. The original
   [HYB-0-GAP-ANALYSIS.md](hybrid/HYB-0-GAP-ANALYSIS.md) was written
   when Track A had only suites/revisions/cases — that premise is now
   stale. **Before HYB-1 starts, the gap analysis must be refreshed
   against the final Track A implementation**, specifically covering
   what didn't exist when the original analysis was written:
   - the cycle and result domain models (`TestCycle`,
     `CycleTestResult`, `CycleResultHistory`);
   - append-only result history and its revision-numbering discipline;
   - the evidence and annotation models (`EvidenceItem`,
     `EvidenceRevision`);
   - the `EvidenceStorage` abstraction and the R2 backend (ADR-0002) —
     HYB-1+ evidence (if any) should plug into this, not invent a
     parallel storage path;
   - actor and evidence provenance conventions (`result_source`,
     `change_source`, `evidence_source`, `captured_by`/`created_by`);
   - authentication, CSRF, CORS, and role-boundary enforcement as it
     now actually exists (Phase 7's `csrf_origin_check`, role checks,
     project isolation);
   - dashboard, reporting, Excel, and ZIP export as they now actually
     exist — any hybrid run data will need to flow into these, not sit
     beside them unintegrated;
   - the hybrid extension fields already reserved in the schema
     (`execution_mode`, `result_source`/`change_source`,
     `runner_run_id`) and which are still correctly unused;
   - the final Track A REST API surface and the frontend execution UI
     (`CycleExecution.jsx`) that HYB-4's pause/resume UI will need to
     integrate with, rather than the HYB-0 spike's console-only runner
     output.
2. Smallest possible **HYB-0 spike** — not the full feature set. Exit
   gate (hybrid doc section 15, HYB-0): a local runner opens a visible
   browser, executes 3 recorded steps, pauses for a human decision,
   resumes, uploads one screenshot, stores an auditable run record. No
   mocked runner output accepted as satisfying this gate. **Done** — see
   below.

Delivery sequence after the spike:

- **HYB-0** — architecture spike. **Done, 2026-08-01** — see
  [HYB-0-GAP-ANALYSIS.md](hybrid/HYB-0-GAP-ANALYSIS.md) (decisions made)
  and [HYB-0-SPIKE-RESULTS.md](hybrid/HYB-0-SPIKE-RESULTS.md) (all 10
  gate criteria passed with recorded evidence — real headed browser,
  semantic locators, outbound-only runner, pause/resume in the same
  session, human decision with identity+timestamp, authenticated
  evidence upload/download, actor-tagged run history, real backend
  throughout, no auto-PASS on failure). Runner code lives in `runner/`
  (Node.js + TypeScript + Playwright). Track A Phases 4–7 (cycles,
  execution, evidence, reporting/export, hardening) were completed after
  this spike, carrying the extension points above into that work.
  **2026-08-02: the user explicitly superseded the "HYB-1 waits on
  Release Closure" ordering** for this delivery — Release Closure's
  three human-operated checks remain unresolved and the project remains
  NOT PRODUCTION READY, but they were reclassified as release blockers
  only, not development blockers, for HYB-1 onward. HYB-1 work proceeds
  on the `feature/hybrid-mvp` branch (not `main`).
- **HYB-1** — workflow model and editor. **Done, 2026-08-02** — see
  [HYB-1-GAP-ANALYSIS-REFRESH.md](hybrid/HYB-1-GAP-ANALYSIS-REFRESH.md)
  for the design decisions (`WorkflowTestCaseLink` carries both stable
  logical identity and the exact immutable `TestCase` snapshot; hybrid
  evidence will reuse `EvidenceItem`/`EvidenceRevision`, not a parallel
  subsystem — implemented starting HYB-4 when runs/checkpoints exist to
  link against). Built: `WorkflowDefinition`/`WorkflowRevision`/
  `WorkflowStep`/`WorkflowTestCaseLink` models (mirrors
  `TestSuite`/`ScriptRevision`/`TestCase`'s exact DRAFT→PUBLISHED→
  SUPERSEDED + clone-for-correction pattern), all 13 MVP step types
  (`NAVIGATE`…`MANUAL_CHECKPOINT`), structured locators (strategy +
  value + fallback JSON, never raw x/y), server-side validation that a
  sensitive step's value must be a `${VAR_NAME}` placeholder (literal
  values are rejected outright, not just discouraged by the UI),
  reorder, publish (ADMIN-only, matching revision publish), clone,
  test-case links, and a real frontend editor (workflow list, revision
  list, step add/edit/delete/reorder, sensitive-variable checkbox,
  manual-checkpoint fields, link picker). Verified: 4 new backend pytest
  tests covering all 14 HYB-1 acceptance-gate items (create/draft/all-
  step-types/reorder/checkpoint/sensitive-var-rejection/link/publish/
  immutable-after-publish/clone/old-revision-unchanged/authorization-
  boundaries/audit-log), full 45-test suite passing (was 41; +4 new),
  frontend production build clean, and a real headed-browser Playwright
  run through the entire editor flow (screenshots confirm the sensitive
  placeholder is what's displayed — never a literal — and that the
  cloned draft correctly copied all 5 steps + the link while the
  original stayed PUBLISHED). One real pre-existing bug found and fixed
  along the way: the login-rate-limit test in
  `test_security_boundaries.py` deliberately exhausted slowapi's
  process-global, IP-keyed limiter and never reset it, silently breaking
  any test file that ran afterward and needed a real login within the
  same test process — fixed with `limiter.reset()`.
- **HYB-2** — runner registration and execution. **Done, 2026-08-02** —
  branch `feature/hybrid-mvp`. `RunnerToken` (master DB) extended with
  registration/heartbeat fields (name/version/platform/capabilities/
  `last_heartbeat_at`) rather than a second `runners` table — one runner
  process still equals one token in this MVP. New project-scoped
  `WorkflowRun`/`WorkflowStepRun`/`RunnerExecutionEvent` tables and a
  real job-claim protocol (`backend/app/routers/workflow_runs.py`):
  outbound-only `/claim` (atomic, SQLite-serialized — a second runner
  racing for the same job gets nothing), a time-limited lease
  (`lease_token`/`lease_expires_at`) renewed via `/heartbeat`, a lazy
  expiry sweep (`_expire_stale_leases`, no cron needed) that marks a
  run `RUNNER_LOST` if its lease lapses, idempotent event delivery
  (`(workflow_run_id, idempotency_key)` unique — a retried POST returns
  the original row), structured `WorkflowStepRun` history distinct from
  the raw event log, and cooperative cancellation (`cancel_requested`
  flag; a `QUEUED` run cancels immediately, a claimed one waits for the
  runner to observe the flag and self-terminate). Evidence upload
  reuses the real `EvidenceItem`/`EvidenceStorage` system exactly as
  decided in `HYB-1-GAP-ANALYSIS-REFRESH.md` — not a parallel table —
  gated on the run being linked to a `cycle_test_result_id` (a
  standalone run with no cycle link cannot upload evidence through this
  endpoint; documented gap, not silently allowed). `runner/` gained a
  second real entry point (`npm run execute`, alongside the untouched
  HYB-0 `npm run spike`): `executionClient.ts` (job protocol client),
  `execution/locators.ts` (structured-locator resolution — `TEST_ID`/
  `ROLE`/`LABEL`/`PLACEHOLDER`/`TEXT`/`CSS`/`XPATH`, never raw x/y — and
  `${VAR_NAME}` sensitive-value resolution against the runner's own
  environment, never logged), `execution/executor.ts` (claims, executes
  a published revision's steps against one persistent Playwright page,
  auto-retrying `ASSERT_TEXT`/`ASSERT_URL` within the step timeout
  rather than checking once, heuristically categorizing failures into
  `FAILURE_CATEGORIES`, pausing cleanly — not faking a resume — at a
  `MANUAL_CHECKPOINT` since checkpoint resume is HYB-4 scope). Frontend:
  `RunnerList.jsx` (register/list/revoke, live ONLINE/STALE/OFFLINE/
  REVOKED status, admin-only) and a "Runs" panel in `WorkflowDetail.jsx`
  (queue, live-polling status, expandable step-run + event history,
  cancel).

  **Two real bugs found and fixed via the actual real-runner run, not
  code review**: (1) the runner's own cancel-check poll (`GET
  /workflow-runs/{id}`) 401'd because that endpoint required a user
  session — the runner only ever holds a token. Fixed with
  `_require_user_or_runner`, the same dual-credential pattern HYB-0's
  `hybrid.py::get_run` already established. (2) `ASSERT_TEXT`/
  `ASSERT_URL` checked the page exactly once immediately after a
  preceding `CLICK`, before the SPA had finished navigating — a false
  failure, not a real one. Fixed with `pollUntil()`, auto-retrying
  within the step's timeout the same way Playwright's own `expect()`
  assertions do.

  Verified: 7 new backend pytest tests (full job protocol including
  duplicate-claim rejection, wrong-lease rejection, idempotent event
  replay, lease-expiry → `RUNNER_LOST`, cooperative vs. immediate
  cancel, evidence-requires-cycle-link, and distinct HUMAN/RUNNER/
  SYSTEM provenance) — full suite **52/52** (45 + 7). Frontend build
  clean. Runner `tsc --noEmit` clean. **Real end-to-end run, not
  mocked**: a real Node.js/TypeScript process launched real headed
  Chromium, claimed a queued run over HTTP, logged into QA-Again's own
  real `/login` page for real (NAVIGATE → FILL email → FILL a sensitive
  `${RUNNER_LOGIN_PASSWORD}` placeholder → CLICK → ASSERT_TEXT →
  SCREENSHOT), and PASSED — confirmed via the API (structured
  `WorkflowStepRun` rows, a real 21,677-byte PNG `EvidenceItem` with
  `evidence_source=RUNNER`, `workflow_run_id` set, visible through
  Track A's own evidence-list endpoint) and via a real headed-browser
  Playwright pass through the actual `RunnerList`/`WorkflowDetail` UI
  (screenshot: runner ONLINE with a live heartbeat; all three attempted
  runs — `RUNNER_LOST`, `FAILED`, `PASSED` — listed with correct status,
  step-by-step results, and provenance-tagged event history). See
  `docs/hybrid/SESSION_HANDOFF.md` for the full verification record.
- **HYB-3** — browser workflow recorder. **Done, 2026-08-02** — branch
  `feature/hybrid-mvp`. New `RecordingSession`/`RecordedStep` tables
  (project-scoped) with the exact same outbound-only claim/lease
  protocol as `WorkflowRun` (HYB-2) — a session is a claimable job, not
  a push target. Recording happens strictly inside a Playwright browser
  the QA Runner itself launches (`runner/src/recorder/domRecorder.ts`,
  an in-page script injected via `page.addInitScript`) — never the
  tester's own browser, never a global OS hook. Captures click,
  change (debounced to one FILL/SELECT/CHECK/UNCHECK per edit, not per
  keystroke), and a narrow keydown allow-list (Enter/Escape outside text
  fields) — no `mousemove` listener exists anywhere in the file. Ranked
  locator generation follows the documented priority (`TEST_ID` → `ROLE`
  +name → `LABEL` → `PLACEHOLDER` → `TEXT` → `CSS` → `XPath`), with
  diagnostic x/y coordinates stored only as optional metadata, never as
  a locator strategy. Sensitive-field detection (password type,
  autocomplete, name/label pattern match) redacts **in-page, before the
  value ever crosses the Node bridge** — `RecordedStepCreate.input_value`
  is `undefined` (not empty-string) for a sensitive field, and the
  backend rejects outright any attempt to send one
  (`recording_sessions.py::append_recorded_step`). A file-input change
  is recorded as a `MANUAL_CHECKPOINT` (file-upload automation is out of
  scope; the real local path is never captured, not even the filename).
  Tester control plane (`RecordingPanel.jsx`): Start/Pause/Resume/Stop/
  Discard, live-polling captured-step list, insert-a-checkpoint,
  per-step "Test locator" (the runner evaluates the exact same
  `resolveLocator()` replay uses against the still-live page and reports
  match count honestly — 0 matches if the target is genuinely gone),
  edit/delete/reorder once STOPPED, and **Save as Draft** — which reuses
  HYB-1's own revision/step-creation code path and its exact validation
  (`_validate_step_fields`), so a recorded draft is indistinguishable
  from a hand-built one. Stopping never auto-publishes; the tester
  publishes manually like any other draft.

  **Three real bugs found and fixed via the actual real recording run,
  not code review** (all in `runner/src/recorder/`): (1) the very first
  NAVIGATE (fired by the recorder's own initial `page.goto`) raced the
  session's still-CLAIMED status and was rejected — fixed by marking
  RECORDING before that navigation. (2) `accessibleName()`'s text
  fallback used a `<select>`'s raw `textContent`, which silently
  concatenates every `<option>`'s text — produced a locator that could
  never resolve; fixed by excluding form controls from the text-fallback
  path entirely (falls through to an honestly-flagged CSS locator
  instead of a fabricated one). (3) **the in-page script's own source
  contained `\s`/`\b` inside an outer JS template literal without double-
  escaping — an unrecognized string escape sequence, so the browser-side
  regex silently became `/s+/g` instead of `/\s+/g`, replacing every run
  of the literal letter "s" with a space** ("HYB3 Test Project" →
  "HYB3 Te t Project") — caught by a real replay `TIMEOUT` failure
  (`getByRole('button', {name: 'HYB3 Te t Project...'})` never matched),
  fixed by correcting the escaping and adding a `flatText()` helper that
  also fixes proper whitespace-joining between child text nodes (raw
  `textContent` doesn't insert the spaces a real accessible-name
  computation does, which had separately caused a multi-word button's
  locator to fail to match too). (4) a genuine **event-ordering race**:
  click events reach Node via the in-page `exposeFunction` bridge while
  NAVIGATE events reach Node via Playwright's own `framenavigated`
  listener — two independent async paths whose network calls could
  complete out of order, occasionally persisting a NAVIGATE before the
  CLICK that caused it. Fixed with a single Node-side FIFO promise queue
  (`enqueueAppend`) shared by both sources.

  Verified: 5 new backend pytest tests (full protocol: claim, dual-
  credential lease enforcement, sensitive-value rejection, idempotent-
  ish step append, pause/resume gating, locator-test request/result,
  stop → review → edit/delete/reorder → save-as-draft →
  `_validate_step_fields` parity with manual authoring, discard wipes
  the buffer, lease-expiry → `RUNNER_LOST`, VIEWER read-only boundary),
  full suite **57/57** (52 + 5). Frontend build clean. Runner
  `tsc --noEmit` clean. **Real end-to-end recording + replay, not
  mocked**: attached to the QA Runner's own launched browser via its
  loopback CDP debug port (opt-in, local-only —
  `RECORDER_DEBUG_PORT`, the same mechanism `playwright codegen` itself
  uses) to simulate a real tester — logged in for real (ordinary email
  input + a genuinely sensitive password field), clicked through real
  page transitions, selected a real dropdown option, checked a real
  checkbox, inserted a manual checkpoint, requested two real locator
  tests (one on a still-present element — matched, one on the Sign-in
  button after navigating away — **honestly reported 0 matches**),
  proved locator survival across a real viewport-resize-and-reflow,
  stopped, reviewed, assigned the sensitive field's `${SECRET_LOGIN_
  PASSWORD}` placeholder, saved as a draft, published, and replayed the
  published revision through the real HYB-2 runner: **all 12 automated
  steps PASSED for real** against the real running app, then correctly
  paused at the `MANUAL_CHECKPOINT` (full resume is HYB-4 scope, exactly
  as HYB-2 already documented). Confirmed **zero occurrences** of the
  real password anywhere it could conceivably have leaked: grepped the
  raw SQLite DB file bytes, the backend's request-timing log, and every
  one of the runner's own console logs across all recording/replay
  attempts this session — all clean.
- **HYB-4** — manual checkpoints and hybrid evidence. **Done, 2026-08-02**
  — branch `feature/hybrid-mvp`. Builds the *resume* side of HYB-2's
  already-proven `MANUAL_CHECKPOINT` pause; the pause mechanics
  themselves are unchanged.

  **Backend** (`backend/app/models.py`/`schemas.py`/`routers/
  workflow_runs.py`, all additive): new project-scoped
  `WorkflowCheckpointDecision` table — append-only, one row per decision,
  `decision_revision_no` per `(workflow_run_id, workflow_step_id)`,
  `source` always `HUMAN`, `decided_by_user_id`/`decided_by_email`/
  `decided_at` always server-derived from the authenticated session
  (`require_tester`), never trusted from the request body.
  **Decision-conflict protection** is not a lock or a queue — the same
  DB transaction that inserts the decision row also flips
  `run.status` away from `WAITING_FOR_HUMAN` (to `RESUMING` for PASS, or
  a terminal status for FAIL/BLOCKED/NOT_APPLICABLE); a second, racing
  decision request finds `run.status` already moved and is rejected
  with `409`, the same "first commit wins" pattern already used for the
  evidence-upload quota race. A repeated request with the same
  `idempotency_key` returns the original row instead of erroring or
  duplicating (checked *before* the `WAITING_FOR_HUMAN` gate, so a
  legitimate retry succeeds even after that exact request's own earlier
  attempt already moved the run on). Reason validation mirrors
  `cycle_results.py` exactly: FAIL requires `actual_result_md`, BLOCKED
  and NOT_APPLICABLE require `reason`; NOT_APPLICABLE enters the same
  admin-review queue (`review_status`/`POST .../review`) as Track A's
  own NOT_APPLICABLE policy — no second policy invented. PASS is
  rejected with `400` if the linked cycle's `require_evidence_for_pass`
  is enabled and no evidence exists yet, exactly like a Track A
  `CycleTestResult` PASS. A LOCKED cycle blocks checkpoint decisions the
  same way it blocks every other Track A mutation.

  The **paused lease**: `WAITING_FOR_HUMAN`/`RESUMING` are now lease-
  tracked (`WORKFLOW_RUN_PAUSED_LEASE_STATUSES`), just on a 300s timeout
  (`PAUSED_LEASE_DURATION_SECONDS`) instead of the 60s active-execution
  one (`LEASE_DURATION_SECONDS`) — a human deciding takes arbitrarily
  long; a 60s lease would false-positive `RUNNER_LOST` on every real
  checkpoint. The *same* `lease_token` stays valid across the entire
  pause (never nulled, never reissued), so resuming never needs a fresh
  `/claim`. `_expire_stale_leases` (the existing lazy sweep, no cron)
  now covers both lease classes — a runner that goes silent while paused
  is marked `RUNNER_LOST` exactly like one that goes silent mid-step,
  and this **never touches an existing decision row**: if none exists
  yet, there's nothing to preserve; if one does (a PASS already flipped
  the run to `RESUMING` and the runner then vanished before
  reconnecting), it's left exactly as recorded.

  New endpoints, all under `/api/{slug}/workflow-runs/{run_id}/`:
  `GET checkpoint` (context: run detail, linked Track A test case(s) at
  their exact revision snapshot, workflow revision, checkpoint
  instructions/expected value, decision history, elapsed waiting time —
  one call, reusing `WorkflowRunDetailOut` rather than a parallel
  shape), `GET/POST checkpoint-decision(s)`, `POST checkpoint-decisions/
  {id}/review` (admin, NOT_APPLICABLE only), and `POST checkpoint-
  resume` (runner-token + lease auth — validates the response belongs to
  the correct run/step/checkpoint/decision before honoring it; a stale
  or mismatched request never resumes anything; idempotent against a
  duplicate resume call from the *same* still-connected runner; a
  *different* runner process — no live browser, no knowledge of this
  `lease_token` — cannot call it at all, the same `_require_lease` check
  every other runner action already uses, so a resume can never be
  fabricated by a fresh process that doesn't actually hold the original
  browser session). `complete_run`'s allowed terminal set now includes
  `RUNNER_LOST` so a still-connected runner that loses its own Chromium
  session while paused can self-report honestly rather than going quiet
  until the lease sweep catches it.

  **Evidence and defects** — no parallel subsystem, exactly as
  `HYB-1-GAP-ANALYSIS-REFRESH.md` decided: `EvidenceItem` gained one
  additive nullable column, `checkpoint_decision_id` (set server-side,
  never client-supplied, when a reviewer attaches evidence while
  deciding). Checkpoint screenshots the runner uploads before pausing
  already use the existing HYB-2 evidence-upload endpoint with
  `evidence_source=RUNNER`; a human reviewer's own upload goes through
  Track A's *own* `POST .../evidence` endpoint (now accepting optional
  `workflow_run_id`/`workflow_step_run_id` form fields, validated
  against the run) rather than a new one, defaulting to
  `evidence_source=HUMAN` exactly as it always has. `Defect` gained
  three additive nullable columns (`workflow_run_id`/
  `workflow_step_run_id`/`checkpoint_decision_id`); `DefectCreate` and
  `DefectUpdate` both accept them, so a checkpoint reviewer can create a
  new defect or link an existing one through the same defect endpoints
  Track A already has.

  **Runner** (`runner/src/execution/executor.ts`/`api/
  executionClient.ts`): the `MANUAL_CHECKPOINT` branch no longer breaks
  the loop and closes the browser. It now creates the checkpoint's own
  `WorkflowStepRun` row, captures and uploads a real screenshot, posts
  `CHECKPOINT_WAITING` (now including page URL/title), then enters
  `waitForHumanDecision()` — an in-process poll loop that keeps
  heartbeating (renewing the paused lease) every cycle, checks
  `page.isClosed()` each iteration (honest Chromium-crash detection —
  self-reports `RUNNER_LOST` rather than fabricating a resume), and
  checks `cancel_requested` (so cancellation while paused works
  cooperatively, same pattern as mid-run cancellation). Once it observes
  `RESUMING`, it calls `/checkpoint-resume`, splices the returned
  remaining steps into the *same* step loop, and continues executing
  against the *same* `page`/`browser` objects — never a fresh
  `chromium.launch()`. A transient network error while polling is
  logged and retried, not treated as loss; the server's own 300s paused-
  lease grace window is what actually decides genuine staleness.

  **Frontend**: `CheckpointPanel.jsx` (new) — rendered inline inside
  `WorkflowDetail.jsx`'s existing expanded-run view whenever a
  `MANUAL_CHECKPOINT` step-run exists for that run. Shows instructions,
  expected result, linked Track A case(s), prior automated step results,
  live elapsed-waiting time (polls every 3s while `WAITING_FOR_HUMAN`),
  decision history with real actor/timestamp, and — reusing
  `EvidenceGallery`/`AnnotationEditor` unchanged, just passed the run/
  step-run ids to tag new uploads with — the exact same screenshot-
  capture/paste/upload/annotate flow Track A's own execution screen
  already has. PASS/FAIL/BLOCKED/NOT_APPLICABLE decision buttons with
  inline reason validation, plus inline "create defect"/"link existing
  defect" using the same `createDefect`/`updateDefect` calls a future
  standalone defects UI would use.

  Verified: 12 new backend pytest tests (full PASS-resume flow with
  evidence-required-for-PASS gating; FAIL is terminal and a racing
  second decision is rejected with `409`, never overwriting it;
  FAIL/BLOCKED reason validation; NOT_APPLICABLE + admin review; decision
  conflict; idempotent retry; `RUNNER_LOST` while paused via lease-
  duration monkeypatching, confirming prior step results and the paused
  state survive; LOCKED-cycle rejection; defect provenance linkage;
  wrong-lease-token resume rejection) — full suite **69/69** (57 + 12).
  Frontend build clean. Runner `tsc --noEmit` clean.

  **Real end-to-end verification, not mocked**: real FastAPI + SQLite
  backend, real Node.js/TypeScript runner, **real headed Chromium**,
  driven entirely through the real HTTP API (curl) to simulate a real
  human tester, against a workflow with a real automated step before and
  after a `MANUAL_CHECKPOINT`. Three separate real runs:
  (1) **PASS + resume**: the pre-checkpoint steps set a `localStorage`
  marker in the browser and asserted it; the runner paused, uploaded a
  real 7,720-byte `SCREENSHOT` evidence item (`evidence_source=RUNNER`),
  a real human PASS decision was submitted with real actor identity
  (`decided_by_email=admin@example.com`) and timestamp; the *same*
  runner process observed `RESUMING`, called `/checkpoint-resume`, and
  continued in the *same* browser session — the post-checkpoint step
  re-read the page and found the marker **still set**, which is only
  possible if the in-memory browser context genuinely survived the pause
  (a fresh `chromium.launch()` would have empty `localStorage`); the run
  reached `PASSED` with all 6 steps green and a full HUMAN→RUNNER
  provenance-tagged event trail (`CHECKPOINT_DECIDED`/HUMAN,
  `RUN_RESUMED`/RUNNER). (2) **FAIL is terminal**: a human FAIL decision
  immediately ended the run `FAILED`; a racing second decision request
  (simulating another tester, or a retry) was rejected `409` and did
  **not** overwrite it; the still-connected runner observed the terminal
  status on its next poll, correctly declined to resume, and exited
  without ever executing the two post-checkpoint steps — confirmed via
  the API that exactly one decision row exists (`status: FAIL`) and only
  4 of 6 step-runs were ever created. (3) **Cancellation while paused**:
  `cancel_requested` was set on a paused run; the runner's poll loop
  observed it on its next cycle and called `/complete` with `CANCELLED`
  itself, closing the browser cleanly. All three runs' full event/
  decision/step-run history was independently confirmed via the API
  afterward. Confirmed no secret values or unrelated local artifacts
  were committed (`runner/.env`, used only for this verification, is
  gitignored and was deleted afterward).
- **HYB-5** — timing, reports, hardening (per-step timing history,
  hybrid execution report, machine-vs-human provenance, export updates,
  `docs/HYBRID_RUNNER_THREAT_MODEL.md`, recovery/retry rules, operator
  and tester guides).

Explicit non-goals for the hybrid MVP (hybrid doc section 13): full
load/stress/soak testing, mobile/desktop app automation, continuous
video, AI autonomous sign-off or final pass/fail decisions, automatic
Git-diff impact analysis, IDE integration, autonomous locator repair,
pixel-diff as final authority, arbitrary scripting, branching/loops,
cloud-scale parallel browser farms, shared auth or two-way sync with
PM-Again, and replacing manual execution as a mode.
