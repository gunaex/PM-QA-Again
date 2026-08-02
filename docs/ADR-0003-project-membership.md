# ADR-0003 — Project-level access control (project membership)

Status: accepted
Date: 2026-08-02

## Context

QA-Again had zero project-level access control: any authenticated user
of any role (ADMIN/TESTER/VIEWER — a single global column, ADR-0001
decision 2) could reach every project by slug. There was also no UI for
user management at all — creating a TESTER/VIEWER account required
`curl`/PowerShell against `POST /api/auth/users` directly, unusable for
a non-technical admin.

The user's requirement: an admin should be able to create TESTER/VIEWER
accounts through the browser, and restrict each one to specific
projects — while ADMIN keeps unconditional access to everything.

## Decision

### A `ProjectMembership` table layered on top of the existing global role

`ProjectMembership(project_id, user_id)` in `master.db` (same database
as `Project`/`User`, plain FK columns — no `relationship()`, matching
every other model in this codebase, which joins manually via
`.query().filter()`). A user's global `role` is unchanged and still
governs *what* they can do (read vs. write vs. admin actions);
`ProjectMembership` governs *which projects* they can reach at all.
ADMIN bypasses this table entirely — no membership row is ever created
or checked for an ADMIN account.

Enforced by a new `require_project_access(slug, ...)` dependency
(`backend/app/auth.py`), which 404s if the project doesn't exist and
403s if the (non-ADMIN) user has no membership row for it. Applied as
the router-level dependency (replacing `get_current_user`) across every
Track A router: `cases.py`, `cycle_results.py`, `cycles.py`,
`dashboard.py`, `defects.py`, `evidence.py`, `exports.py`, `reports.py`,
`revisions.py`, `signoffs.py`, `suites.py`, plus per-endpoint in
`quick_test.py` (which has no router-level dependency) and
`projects.py`'s own `GET /{slug}` and `GET /{slug}/storage-quota`.

**Bonus, not a design goal**: `get_project_db(slug)` never checked the
master-DB `Project` table before this — any slug silently
auto-provisioned an empty SQLite file. Since `require_project_access`
runs first in every route above, this closes that latent gap as a free
side effect.

### Zero access by default — no auto-grant, no backfill

A newly created TESTER/VIEWER account starts with **no** project
access. An admin must explicitly grant each project via the new
`/users` page (or the underlying `POST /api/auth/users/{id}/projects`
endpoint). No migration backfills existing accounts to "all projects" —
a deliberate choice over the alternative (grandfather everyone in) to
avoid quietly widening access for existing non-admin accounts the first
time this ships.

### Project creation becomes ADMIN-only

`POST /api/projects` moved from `require_tester` to `require_admin`.
Previously a TESTER could create a project and would (implicitly) reach
it since there was no membership check at all; now that access is
always explicit, letting a TESTER create-and-therefore-access a project
would be an inconsistent backdoor around the model this ADR just
introduced. An admin creates the project, then assigns it.

### Enforcement scope: Track A only (this pass)

Hybrid/Runner endpoints (`workflows.py`, `workflow_runs.py`,
`recording_sessions.py`, `hybrid.py`, `hybrid_reports.py`) are
deliberately **not** gated by `require_project_access` in this change.
Reasons:
- Several of their endpoints are authenticated by `RunnerToken`
  (`get_current_runner`), not a `User` at all — `ProjectMembership` has
  no meaning for a runner process.
- The project-runner trust boundary is a separately documented, known
  gap (`docs/HYBRID_RUNNER_THREAT_MODEL.md` §4: "no per-project runner/
  user authorization boundary... appropriate for a single trusted
  organization, not a genuine multi-tenant deployment"). Folding
  human-user project membership into that same pass would conflate two
  different trust boundaries instead of addressing the documented one
  directly.
- Keeps this change's blast radius to exactly what was asked for: human
  testers/viewers browsing the web UI.

Revisit as a follow-up ADR if/when the hybrid runner's own multi-tenant
boundary gets addressed.

## Consequences

- Every existing test using the session-scoped `auth_client` fixture
  (an ADMIN session, `tests/conftest.py`) is unaffected — ADMIN never
  needs a membership row.
- Two existing tests that exercised a VIEWER against Track A endpoints
  (`test_security_boundaries.py::test_viewer_can_read_but_not_write`,
  `test_evidence_security.py::test_viewer_can_download_evidence_but_not_upload_or_archive`)
  needed an explicit membership grant added to their setup, so they keep
  asserting the *role* boundary they're meant to, not incidentally
  passing/failing on the new *access* boundary instead.
- `ProjectList.jsx`'s "New Project" form is now ADMIN-only
  (`canCreate = isAdmin`), matching the backend change.
- A `/users` page (ADMIN-only, alongside the existing `/runners` page)
  now exists for creating accounts and managing project access entirely
  through the browser.
