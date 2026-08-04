# User access and running-number test script

Use this focused script before merging `feature/hybrid-mvp`. Run it against a
disposable project and disposable accounts. Do not use real passwords.

## Scope and current design

- A user has one **global role**: `ADMIN`, `TESTER`, or `VIEWER`.
- `TESTER` and `VIEWER` receive project access one user at a time.
- `ADMIN` automatically reaches every project and has no project assignment
  toggles.
- The current UI sets a role while creating a user. It cannot change an
  existing user's role.
- There is no bulk rule such as "assign Project A to every TESTER".
- Test-case codes are suggested by the browser, but are not a backend-owned
  running-number service. See the numbering checks below.

Record each result as `PASS`, `FAIL`, or `BLOCKED`, and attach a screenshot plus
the failed request's status code/response body for every `FAIL`.

## Test data

Create two disposable projects:

- `Access Test A`
- `Access Test B`

Create these disposable accounts with temporary passwords:

- `access.tester@example.com` — `TESTER`
- `access.viewer@example.com` — `VIEWER`
- `access.admin@example.com` — `ADMIN`

## A. Create users and assign global roles

1. [ ] Log in as the bootstrap admin and open **Users**.
2. [ ] Create the TESTER account. Confirm the row shows `TESTER`, Active, and
       `Password change pending`.
3. [ ] Create the VIEWER account and confirm the same states with role
       `VIEWER`.
4. [ ] Create the ADMIN account. Confirm its row says **All projects**, not
       **Manage projects**.
5. [ ] Try creating the TESTER email again. Expect a clear duplicate-email
       error and no second account.
6. [ ] Log in with each temporary password. Expect a forced password change
       before normal application use.
7. [ ] As TESTER and VIEWER, navigate directly to `/users`. Expect rejection;
       user management must remain ADMIN-only.
8. [ ] Deactivate the TESTER from **Users**. Expect subsequent authentication
       to be rejected. Reactivate it and confirm login works again.

Expected current limitation:

- [ ] Confirm there is no Edit Role control on an existing row. Changing
      `TESTER` to `VIEWER` after creation is **not implemented**; record this as
      `KNOWN GAP`, not a failed regression test.

## B. Assign projects to individual users

1. [ ] Before granting access, log in as TESTER. Expect an empty project list
       with an explanation that no projects are assigned.
2. [ ] As ADMIN, expand **Manage projects** for the TESTER and enable only
       `Access Test A`. Expect the toggle to turn green without reloading.
3. [ ] In the TESTER's existing session, refresh Projects. Expect Test A to be
       visible and Test B to be absent.
4. [ ] Open Test A as TESTER. Expect authoring and execution actions to work.
5. [ ] Navigate directly to Test B's URL. Expect HTTP `403`, not leaked data.
6. [ ] Grant Test B to the same TESTER. Expect both projects to appear.
7. [ ] Revoke Test A while the TESTER remains logged in. Refresh and directly
       revisit Test A. Expect access to disappear immediately without login.
8. [ ] Grant Test A to VIEWER. Expect read pages to work, but create, edit,
       execute, publish, archive, and user-management actions to be unavailable
       or rejected.
9. [ ] Confirm ADMIN sees both projects without project toggles or membership
       assignments.

Expected current limitation:

- [ ] Confirm project access must be toggled separately for each user. Bulk
      assignment by role, such as "all TESTER users", is **not implemented**;
      record this as `KNOWN GAP`.

## C. Test-case running-number behavior

1. [ ] In Test A, create a suite and a new draft revision with no cases.
2. [ ] Click **Add Case**. Expect the checkpoint code suggestion `TC-001`.
3. [ ] Save it, then click **Add Case** again. Expect `TC-002`.
4. [ ] Replace the codes with `REG-P0-001` and `REG-P0-002`, then add another
       case. Expect the suggestion `REG-P0-003`.
5. [ ] Manually change the suggestion to a different valid code and save.
       Expect it to be accepted; the suggestion is intentionally editable.
6. [ ] Attempt to save a duplicate checkpoint code in the same revision.
       Expect a clear duplicate error.
7. [ ] Create a different revision and add a case using the same checkpoint
       code. Expect it to be accepted because uniqueness is per revision.
8. [ ] Open two browser windows on the same revision, click **Add Case** in
       both before either saves, and compare suggestions. Both may suggest the
       same number; after one saves, the other should receive a duplicate error.

Assessment rule:

- Steps 1–7 describe current intended behavior.
- Step 8 demonstrates that this is a UI suggestion, **not an atomic backend
  running number**. If the requirement is a guaranteed project-wide number,
  the feature is incomplete.

## D. Other generated identifiers

1. [ ] Create two defects in Test A. Expect `DEF-1`, then `DEF-2`.
2. [ ] Create the first defect in Test B. Expect `DEF-1` because defect numbers
       are currently per project.
3. [ ] Delete a defect if the UI/API permits it, then create another. Confirm
       whether gaps are retained; do not assume contiguous numbering.
4. [ ] Create and save automated-test revisions. Expect the UI to suggest
       labels such as `v1`, `v2`; confirm the label remains editable.

Known risks to report:

- Defect keys are generated from the current maximum database ID and are not a
  configurable numbering policy.
- Test-case codes, suite codes, cycle codes, and revision labels do not share a
  central numbering service.
- Prefix, padding, reset scope, gap policy, and concurrency guarantees have not
  been defined as one product requirement.

## E. Release decision

Do not approve the access-control portion unless all of A1–A8 and B1–B9 pass.

Choose one explicit numbering decision before release:

- [ ] Accept current behavior: editable suggestions plus per-revision
      uniqueness and per-project `DEF-N` identifiers.
- [ ] Block release and implement a backend-owned running-number policy after
      defining entity, prefix, padding, reset scope, gap reuse, and concurrency
      behavior.

## Result summary

- Date / environment:
- Tester:
- User and global-role result:
- Individual project-access result:
- Role-based bulk assignment result (`KNOWN GAP` today):
- Running-number decision:
- Findings / screenshots:
- Release recommendation:
