# Technical Handover

Written at the end of Phase 7 (2026-08-01) for whoever picks up this
codebase next — a new engineer, a future session, or the original team
returning after a gap. Read this alongside `docs/ROADMAP.md` (what's
built, phase by phase) and the ADRs in `docs/` (why each foundational
decision was made).

## 1. Architecture in one page

```
frontend/   React 19 + Vite + Tailwind v4 + react-router-dom v7 + axios
            → Cloudflare Pages (static build)

backend/    FastAPI + SQLAlchemy, no Alembic (additive column patches)
            → Fly.io, one persistent volume

runner/     Node.js + TypeScript + Playwright (HYB-0 spike only)
            → runs on a tester's own machine, not deployed

Evidence binaries → Cloudflare R2 (private bucket, S3-compatible API)
Everything else (users, projects, suites, revisions, cases, cycles,
results, evidence metadata, defects, sign-offs) → SQLite, one file per
project + one master.db for cross-project registry/users.
```

Every architectural decision has a written ADR — read them before
changing the foundation, not just the code:

- `ADR-0001-rebuild-foundation.md` — why FastAPI/SQLite/PM-Again
  conventions, roles model, export approach.
- `ADR-0002-evidence-storage-r2.md` — why R2, the storage abstraction,
  the failure-handling model for uploads.
- `adr/ADR-HYB-001-playwright-hybrid-execution.md` — why the "no
  Playwright automation" non-goal was superseded, and what didn't
  change.

## 2. Domain invariants — do not casually break these

- **A published `ScriptRevision` is never edited in place.** Corrections
  clone into a new DRAFT. This is the single most load-bearing
  invariant in the app — cycles reference an exact revision, and every
  report/export's traceability depends on that revision never having
  silently changed underneath a cycle that already ran against it.
- **Evidence originals are immutable.** Annotations are append-only
  revisions (design-state JSON, not re-rendered images) layered on top,
  never a replacement of the original bytes.
- **A locked cycle rejects all result/evidence mutation.** Reopening is
  admin-only, requires a reason, and is audit-logged.
- **Every project is its own SQLite file.** Never add a `project_id`
  column to a per-project table — the file *is* the project boundary.
  This is also why cross-project queries are structurally impossible,
  not just filtered out.
- **Additive-only schema changes.** `ensure_columns()` +
  `*_COLUMN_PATCHES` dicts — never remove or rename an existing column
  this way. A genuine breaking change needs its own decision, documented,
  not silently patched.
- **Evidence upload order matters**: validate → quota check →
  idempotency check → write to storage → insert DB row, with a
  compensating delete if the DB insert fails after a successful storage
  write, and a post-commit quota re-check that self-evicts on a detected
  race. Don't reorder this without re-reading ADR-0002's failure-handling
  table and the tests in `test_evidence_storage.py`/
  `test_evidence_concurrency.py`.
- **No hard-delete anywhere in the domain model.** Archive (evidence,
  eventually maybe cycles/suites) is the only "removal" the API exposes.
  A real purge/retention feature is a deliberate future addition, not an
  oversight.

## 3. Extension points already in the schema, deliberately unused

These exist so Track B (hybrid) doesn't require a schema migration to
land — they default to the manual/human values every current row
actually has:

- `CycleTestResult.execution_mode` (`MANUAL|AUTOMATED|HYBRID`),
  `.result_source` (`HUMAN|RUNNER|SYSTEM`), `.runner_run_id` (nullable).
- `CycleResultHistory.change_source` (same enum as `result_source`).
- `EvidenceItem.evidence_source` (same enum).

**Not** added, deliberately: `step_kind`, `checkpoint_status`,
`evidence_source` at the workflow-step level — they only mean something
once `workflow_steps` (HYB-1) exists. Don't add speculative columns for
entities that don't exist yet.

## 4. Known limitations at handover time

| Limitation | Status | Where documented |
|---|---|---|
| Real Cloudflare R2 staging smoke test | **Done** — passed 2026-08-02, human operator | `docs/RELEASE_CHECKLIST.md`, `docs/RELEASE_REHEARSAL.md` |
| Screen Capture API / clipboard-paste | Implemented, real-browser acceptance evidence not yet collected (headless-incompatible, needs a human operator) — **still blocks production release** | `docs/RELEASE_CHECKLIST.md`, `docs/THREAT_MODEL.md` §10 |
| Hybrid execution (Track B, HYB-0–HYB-5) | **Complete** — see `docs/ROADMAP.md` Track B and `docs/hybrid/HYBRID_GUIDES.md` | `docs/ROADMAP.md` |
| RunnerToken global (not per-project) scope | **Accepted for internal MVP only**, under documented controls — not suitable for public multi-tenant deployment | `docs/HYBRID_RUNNER_THREAT_MODEL.md` §4, this section below |
| Hard delete / evidence purge | Deliberately not built | `docs/EVIDENCE_STORAGE_LIFECYCLE.md` |
| Markdown (SATL-style) test-script importer | Deferred — no fixture document in this workspace | `docs/ROADMAP.md` Phase 3 |
| User management UI | API-only, no frontend screen | `docs/guides/ADMIN_GUIDE.md` |
| Per-endpoint rate limiting beyond login | Not built — accepted risk at current scale | `docs/THREAT_MODEL.md` §9 |
| Backups | Script exists (`scripts/backup_databases.py`), not scheduled/automated | `docs/BACKUP_RESTORE.md` |
| Orphan reconciliation | Script exists, not scheduled — manual/periodic | `docs/EVIDENCE_STORAGE_LIFECYCLE.md` |
| Streaming export for very large cycles | Not built — in-memory generation has a documented comfortable ceiling | `docs/CAPACITY.md` |

### RunnerToken internal-MVP release decision (2026-08-02)

`RunnerToken` (the hybrid runner's execution credential) is a global,
not per-project, credential — see
`docs/HYBRID_RUNNER_THREAT_MODEL.md` §4 for the full technical
reasoning (it has always matched the same no-per-project-membership
trust model every human user already has in this app).

**Release decision**: this is **temporarily accepted for INTERNAL MVP
DEPLOYMENT ONLY**, under these controls:

- Deployment is restricted to trusted internal users only.
- The runner token is stored only as a deployment secret (e.g. `fly
  secrets set` or the runner host's own protected environment) — never
  in frontend code, logs, documentation, or source control.
- Runner registration and revocation (`POST /api/runner-tokens`, `PUT
  .../revoke`) are operational and exercised — see
  `docs/hybrid/RUNNER_CREDENTIAL_ROTATION.md`.
- The credential-rotation procedure has been verified (see that same
  document).
- Only approved, known runner machines receive credentials — token
  distribution is a manual, deliberate act by an ADMIN, not
  self-service.
- **A post-MVP backlog item exists**: project/environment-scoped
  runner credentials (adding a `project_id` to `RunnerToken` and
  enforcing it on every runner-authenticated endpoint) — not
  implemented, tracked as future work, not silently deferred without a
  record.
- **Public or customer-facing multi-tenant deployment remains blocked**
  until that project-scoping work exists. Do not describe the current
  global-token model as suitable for that use case under any
  circumstances.

## 5. Operational tasks a new operator needs to know about

- Run `scripts/backup_databases.py` regularly (not automated — set up a
  Fly scheduled machine or external cron).
- Run `scripts/reconcile_evidence.py --confirm` periodically (dry-run by
  default; review its output before adding `--confirm`).
- Watch backend logs for `ORPHANED EVIDENCE OBJECT` (ERROR level) — the
  one case the upload flow's own compensating cleanup can't self-heal.
- Rotate `JWT_SECRET_KEY` and R2 credentials per `docs/DEPLOYMENT.md`'s
  secrets table when required by your org's policy — neither is
  automated.

## 6. Future HYB phases (Track B), if this project continues

HYB-0 (architecture spike) is done and verified — see
`docs/hybrid/HYB-0-SPIKE-RESULTS.md`. Per the user's explicit
instruction at the time, HYB-1 was **not** started; Track A (Phases
0–7) was finished first. If Track B resumes:

- **HYB-1** — workflow model and editor (`workflow_definitions`,
  `workflow_revisions`, `workflow_steps`, draft/publish/clone, test-case
  links, manual checkpoint editor). This is where `step_kind`/
  `checkpoint_status` finally get real meaning.
- **HYB-2** — runner registration and execution (the full `runners`
  table with heartbeat/capabilities, replacing HYB-0's single
  pre-shared token; job claim protocol; execution state machine).
- **HYB-3** — recorder (semantic locator capture, sensitive-input
  handling, draft workflow generation).
- **HYB-4** — hybrid checkpoint and evidence (pause/resume UI wired into
  the real execution screen, not just the HYB-0 spike's console output).
- **HYB-5** — timing/reports/hardening, including a fresh
  `docs/HYBRID_RUNNER_THREAT_MODEL.md` (this document's §10 explicitly
  scopes hybrid execution as out of this threat model).

Read `docs/hybrid/HYB-0-GAP-ANALYSIS.md` before starting HYB-1 — it
records the decisions (REST polling not WebSockets, minimal runner-token
table not full registration, project-scoped tables) that HYB-1/HYB-2
will need to either build on or deliberately supersede.

## 7. Where to start reading code

1. `backend/app/models.py` — the whole domain model in one file, heavily
   commented with the "why" behind non-obvious choices.
2. `backend/app/routers/cycle_results.py` and `evidence.py` — the two
   most invariant-heavy pieces of business logic (validation rules,
   locked-cycle guards, the upload failure-handling sequence).
3. `frontend/src/pages/CycleExecution.jsx` — the single largest/most
   central frontend page, ties together results, evidence, and
   annotation.
4. `docs/ROADMAP.md` — read top to bottom for the full build history and
   every documented decision/gap along the way.
