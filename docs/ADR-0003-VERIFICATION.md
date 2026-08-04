# ADR-0003 (Project Membership) + Hotfix Verification

Verifies the project-membership access-control feature (ADR-0003), the
new `/users` page, and three hotfix items reported during human manual
testing per `docs/MANUAL_TEST_SCRIPT.md`.

## Environment

Isolated backend (`uvicorn`, fresh SQLite `DATA_DIR`) and frontend
(`vite`), both on `127.0.0.1` (matching hostnames — see
`docs/hybrid/REPORTS_REDESIGN_VERIFICATION.md` for why mixing
`localhost`/`127.0.0.1` breaks `SameSite=Lax` cookies). Browser launched
via the tracked-lifecycle helper (`runner/scripts/lib/browserLifecycle.mjs`).

## 1. Automated backend tests

`cd backend && pytest` — **121 passed** (up from 115: +6 new
project-membership tests in `test_security_boundaries.py`, covering:
TESTER with no membership forbidden (403) / nonexistent slug (404),
TESTER scoped to one project can't reach another, revoking membership
blocks access immediately without re-login, ADMIN bypasses membership
entirely, `GET /api/projects` is scoped correctly per role, and TESTER
can no longer create a project).

Two pre-existing tests needed an explicit membership grant added to
their setup so they keep testing the *role* boundary they were written
for, not incidentally passing/failing on the new *access* boundary
instead: `test_security_boundaries.py::test_viewer_can_read_but_not_write`,
`test_evidence_security.py::test_viewer_can_download_evidence_but_not_upload_or_archive`.

## 2. Frontend build/lint

`npm run build` and `npm run lint` — both clean (only pre-existing,
unrelated warnings in `RecordingPanel.jsx`/`CycleExecution.jsx`).

## 3. Real-browser verification — project membership (ADR-0003)

Full flow driven end-to-end in a real headed Chromium instance:

| Step | Result |
|---|---|
| Admin UI login | PASS |
| `/users` page reachable from nav (ADMIN-only) | PASS |
| Create a TESTER via the UI, confirmation banner shown | PASS |
| New TESTER starts with **zero** project access (no toggle pre-checked) | PASS |
| Admin grants project access via a single click on the project's toggle button | PASS |
| TESTER logs in (forced password change first), sees **exactly** the granted project and nothing else | PASS |
| TESTER can open and use the granted project's dashboard | PASS |
| Admin revokes access via the same toggle | PASS |
| TESTER's session (same cookie, no re-login) immediately loses access | confirmed via the backend security tests (`test_revoking_membership_blocks_further_access_without_relogin`) — the real-browser pass exercised the grant/revoke UI itself; the immediate-effect assertion is covered at the API layer with the same precision a browser reload would show |
| Admin's own access to the project is unaffected throughout | PASS (HTTP 200 confirmed independently via a direct API call using the admin's session cookie) |

Console errors observed: two `403 Forbidden` resource-load errors, both
expected (from the deliberate zero-access check before the grant) — no
unexpected errors.

Screenshots captured (not committed): `users-page-empty.png`,
`users-page-created.png`, `users-page-manage-projects-before.png`
(zero access), `users-page-manage-projects-after-grant.png` (checked
toggle), `tester-scoped-project-list.png` (exactly one project visible
to the TESTER), `users-page-manage-projects-after-revoke.png`.

**Test-harness note**: an earlier run of the verification script hit a
false failure navigating straight from the admin's `/users` page,
through a tester login/forced-password-change, expecting to land back
on `/`  — this was the script relying on ambiguous post-login redirect
behavior across a role switch, not a product defect (confirmed by
force-navigating to `/` explicitly, after which every assertion passed
cleanly and repeatably).

## 4. Hotfixes (reported during human manual testing, TC-009/TC-013/TC-015)

### TC-015 — Quick Manual Test "not found" error (investigated, not reproduced)

Tested `POST /{slug}/quick-test` directly against a clean instance
running this session's code:
- As ADMIN: **HTTP 200**, a real cycle + result created correctly.
- As a TESTER with no project grant: **HTTP 403** `"You do not have
  access to this project"` — the expected, correct ADR-0003 behavor,
  not "not found".

The reported "not found" message does not match this behavior. Most
likely explanation: the account that hit it was a pre-existing
TESTER/VIEWER account with no project-membership grant, evaluated
against a build that predates a clearer error path, or the live dev
backend that was tested against was still running the pre-ADR-0003
process image (no `--reload`, so on-disk code changes don't apply
until the process restarts). **Action for the reporter**: retry against
a freshly restarted backend; if "not found" (not a 403 with an access
message) still appears, please attach the browser Network tab response
body for the failing `POST /{slug}/quick-test` call so the exact source
can be pinpointed.

### TC-009 — Checkpoint code auto-numbering + priority dropdown

`frontend/src/pages/RevisionDetail.jsx`: clicking **+ Add Case** now
pre-fills the checkpoint code field with a suggested next value
(`suggestNextCheckpointCode`, matches the most common existing
prefix+trailing-number pattern in the revision, e.g. `REG-P0-001` →
suggests `REG-P0-002`; falls back to `TC-001` for an empty revision).
The field stays fully editable — nothing is enforced server-side beyond
the existing per-revision uniqueness check. Priority changed from a
free-text input to a `<select>` (`P0`/`P1`/`P2`/`P3`/not-set).

Verified in a real browser: seeded one case `REG-P0-001`, opened **+
Add Case**, confirmed the field pre-filled with exactly `REG-P0-002`
and that priority renders as a dropdown. Screenshot:
`hotfix-checkpoint-code-suggest.png`.

### TC-013 — Environment dropdown on Test Cycle creation

`frontend/src/pages/CycleList.jsx`: the free-text Environment field on
**New Cycle** is now a `<select>` with `NON-PROD`/`PROD`/`UAT`/`STR`/
`Other`; choosing `Other` reveals a free-text input for a custom value
(the value actually submitted to the backend, which is unchanged — the
backend already accepted any string).

Verified in a real browser: confirmed the dropdown renders with all
five options. Screenshot: `hotfix-environment-dropdown.png`.

## 5. Process cleanliness

Zero `qa-again-playwright-*` Chrome processes remained after the full
verification session (confirmed via `Win32_Process`), consistent with
every prior verification pass in this project.

## What this does not close

- TC-015 is not resolved — it could not be reproduced against current
  code; see the reporter action item above.
- The three human-operated Release Closure checks (R2 staging smoke
  test, Screen Capture acceptance, clipboard-paste acceptance) remain
  outstanding. **Not production-ready.**
- Hybrid/Runner endpoints remain outside ADR-0003's enforcement scope
  by design (see the ADR) — not a gap in this pass, a deliberate,
  documented boundary.
