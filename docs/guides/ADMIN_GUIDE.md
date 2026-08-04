# QA-Again — Administrator Guide

Everything in the Tester Guide, plus the admin-only actions below.
Read `docs/guides/TESTER_GUIDE.md` first for the core execution workflow.

## User management

**Users** page (top nav, ADMIN-only, next to **Runners**) — no terminal
needed:

1. Fill in email, a temporary password, and a role (`ADMIN`, `TESTER`,
   `VIEWER` — still a single global column per ADR-0001, not
   per-project), click **Create User**. New accounts are forced to
   change their password on first login.
2. For a TESTER/VIEWER row, click **Manage projects** to see every
   project as a toggle button — click a project to grant or revoke that
   account's access to it. **A new TESTER/VIEWER starts with zero
   project access until you assign one** (ADR-0003) — nothing is
   auto-granted.
3. **Deactivate**/**Reactivate** on a row blocks/restores that
   account's ability to log in at all, without deleting it.

ADMIN accounts always see and can act on every project — they never
need (or show) a project-membership list.

Still API-only, no UI yet: revoking a user outright (deactivate is the
closest equivalent today) beyond the active toggle above.

```bash
# Equivalent API calls, if you need them directly:
curl -b cookies.txt -X POST https://api.qaagain.<domain>/api/auth/users \
  -H "Content-Type: application/json" \
  -d '{"email":"new.tester@company.com","password":"TempPass123!","role":"TESTER"}'
curl -b cookies.txt -X POST https://api.qaagain.<domain>/api/auth/users/<user_id>/projects \
  -H "Content-Type: application/json" -d '{"project_id": <project_id>}'
```

List existing users: `GET /api/auth/users`. List/grant/revoke a user's
project access: `GET|POST /api/auth/users/{id}/projects`,
`DELETE /api/auth/users/{id}/projects/{project_id}`.

## Project lifecycle

- **Create**: Projects page → **New Project** (name + optional linked
  PM-Again URL) — **ADMIN-only** (ADR-0003). After creating it, go to
  **Users** to grant whichever TESTER/VIEWER accounts need access —
  nothing is auto-granted, not even to the admin who created it (ADMIN
  already reaches every project unconditionally).
- **Archive/Unarchive**: on a project card → requires re-entering your
  own password (a deliberate extra confirmation for a consequential,
  hard-to-reverse-feeling action, even though archive itself is
  reversible).
- **Delete**: same password confirmation, but this is genuinely
  destructive — the project's entire SQLite file and all its evidence
  metadata are removed. There is no undo short of restoring from a
  backup (`docs/BACKUP_RESTORE.md`). Evidence *objects* in R2 are not
  automatically deleted by a project delete today — a known gap, see
  "What's not built yet" below.

## Revision publishing and correction

Only you (ADMIN) can **Publish** a draft revision — this is deliberate
(the rebuild spec calls for admin review between an unreviewed
import/draft and an immutable publish). Testers can create drafts,
import cases, and clone-for-correction, but only you finalize.

## Cycle control

- **Lock Cycle**: freezes every result/evidence in the cycle — no
  further mutation until you reopen it. Use this once a cycle is
  genuinely complete and you want its results to stand as the record.
- **Reopen**: requires typing a reason (a JS prompt, currently) — this
  is audit-logged (`activity_log` table) so there's a permanent record
  of who reopened what and why.

## Reviewing N/A results

A result marked NOT_APPLICABLE sits in an `UNREVIEWED` state until you
**Accept** or **Request changes** on it (visible in the execution screen
when you select that case). An unapproved N/A still counts against the
pass-rate denominator and blocks go-live readiness if the case is P0 —
reviewing it promptly matters for the dashboard being accurate.

## Storage quota

**Reports** page → **Project Storage Usage** report, or directly:

```bash
curl -b cookies.txt https://api.qaagain.<domain>/api/projects/<slug>/storage-quota
curl -b cookies.txt -X PUT https://api.qaagain.<domain>/api/projects/<slug>/storage-quota \
  -H "Content-Type: application/json" \
  -d '{"storage_quota_bytes": 10737418240, "storage_warning_thresholds": [70,85,95,100]}'
```

Uploads are hard-blocked once a project would exceed its quota — raise
the quota (above) or have testers archive evidence that's no longer
needed (archiving does not free quota — see
`docs/EVIDENCE_STORAGE_LIFECYCLE.md`).

## Sign-offs

`POST /api/{slug}/cycles/{cycle_id}/signoffs` — records a QA_REVIEW,
BUSINESS_ACCEPTANCE, or GO_LIVE decision (APPROVED/REJECTED/PENDING)
with your identity and a timestamp, permanently (never edited in place —
each decision is its own row, visible in the Reports page's Audit/
Sign-off Summary and the Excel export's `06_Sign_Off` sheet).

## Operational tasks (see the linked docs for full procedures)

- **Backups**: `docs/BACKUP_RESTORE.md` — run `scripts/backup_databases.py`
  regularly; not automated yet.
- **R2 credential rotation**: `docs/EVIDENCE_STORAGE_LIFECYCLE.md`.
- **Orphan/reconciliation checks**: `scripts/reconcile_evidence.py`
  (dry-run by default).
- **Capacity thresholds**: `docs/CAPACITY.md`.
- **Deploying/rolling back**: `docs/DEPLOYMENT.md`.

## What's not built yet (be aware, not surprised)

- No UI for defect creation/editing or sign-off recording — API-only
  for now (user management and project-access assignment now have a UI
  — see "User management" above).
- Deleting a project does not cascade-delete its R2 evidence objects —
  they become orphans, caught by the next reconciliation run
  (`scripts/reconcile_evidence.py`), not deleted immediately. If you
  delete a project, consider running reconciliation for it shortly after.
- No hard-delete/purge for individual evidence items — archive only.
- Hybrid (automated/robot) execution is not enabled beyond an
  architecture spike (HYB-0) — every result today is manual/human.
