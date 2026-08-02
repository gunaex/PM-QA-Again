# QA-Again — Manual Test Script

This is a human-executable test script covering every feature of
QA-Again: Track A (manual test management) and Track B (hybrid
automated/manual execution, HYB-1 through HYB-5), plus the browser
process cleanup fix. It exists so a human tester can walk through the
whole product end-to-end and produce real, dated evidence that it
works — a level of proof an AI's own claim of "verified" cannot
substitute for.

## How to use this document

- Work through sections in order — later sections assume data created
  in earlier ones (a project, a suite, a cycle, a workflow).
- Each step has an expected result. Mark `[x]` when it matches, or
  leave `[ ]` and write what actually happened underneath it.
- Anything marked **(ADMIN)**, **(TESTER)**, or **(VIEWER)** requires
  that role — see [Section 1](#1-accounts-and-roles) to set up all
  three before you start.
- Anything marked **(API)** has no UI yet — use `curl` or a tool like
  Postman/Insomnia against the backend directly. An example command is
  given.
- Anything marked **(Hybrid)** is Track B (automated runner /
  recorder). It requires Node.js and the `runner/` package installed —
  see [Section 15](#15-hybrid-runner-installation).
- Record your findings in [the sign-off section](#sign-off) at the end.

---

## 0. Environment setup

- [ ] Start the app locally: run `start.ps1` (Windows) from the repo
      root, or start `backend` (`uvicorn app.main:app --port 8000`) and
      `frontend` (`npm run dev`) manually.
- [ ] On first run against an empty database, the backend console
      prints a one-time generated admin password (or uses
      `ADMIN_EMAIL`/`ADMIN_PASSWORD` if you set them first). Note it
      down.
- [ ] Open `http://localhost:5173/login` — the QA-Again login page
      loads with no console errors (aside from the expected pre-login
      `/auth/me` 401 probe).

---

## 1. Accounts and roles

QA-Again has three global roles: `ADMIN`, `TESTER`, `VIEWER` — still a
single global column per user (ADR-0001), but since ADR-0003 each
non-ADMIN account also only reaches the specific projects an admin has
explicitly granted it (see Section 2a).

1. [ ] **(ADMIN)** Log in with the bootstrap admin account. You should
       be forced to set a new password immediately (`must_change
       password` flow) — confirm this happens and that the new
       password works on the next login.
2. [ ] **(ADMIN)** Top nav → **Users** (only visible to ADMIN) → fill in
       email `tester1@example.com`, a temporary password, role
       `TESTER`, click **Create User**. Confirm a confirmation banner
       appears and the account shows up in the list below.
3. [ ] **(ADMIN)** Create a second account the same way,
       `viewer1@example.com`, role `VIEWER`.
4. [ ] **(ADMIN)** Confirm both new rows show **Manage projects** (not
       "All projects", which only ADMIN rows show) and, before granting
       anything, that expanding "Manage projects" shows no project
       toggled on — zero access by default.
5. [ ] Log in as `tester1` — confirm the forced password-change flow
       triggers on this first login too, and that the Projects page is
       empty with the message "No projects assigned to your account yet
       — ask an admin to grant you access" (not the "create one" message
       ADMIN sees).
6. [ ] Log in as `viewer1` — same forced password-change check and
       empty-with-explanation project list.
7. [ ] Log out and log back in as each account at least once — confirm
       the session persists (you land signed-in, not back at
       `/login`).
8. [ ] **(ADMIN, API, optional)** Confirm the underlying endpoints still
       work directly if you ever need them outside the UI:
       `GET /api/auth/users`, `GET/POST /api/auth/users/{id}/projects`,
       `DELETE /api/auth/users/{id}/projects/{project_id}`.

---

## 2. Project management

Do this section as **(ADMIN)**.

1. [ ] Projects page (`/`) → **New Project** → give it a name (e.g.
       `Manual Test Script Run`) and, optionally, a linked PM-Again
       URL. Confirm it appears in the project list with a generated
       slug. Confirm this button is **not visible at all** if you're
       logged in as `tester1`/`viewer1` from Section 1 (project
       creation is ADMIN-only, ADR-0003).
2. [ ] Open the project — confirm you land on its Dashboard, showing
       "No data yet" (no cycle exists yet).

### 2a. Project access (ADR-0003)

1. [ ] **(ADMIN)** Log back in as admin if needed. **Users** page →
       expand **Manage projects** on the `tester1` row → click the
       `Manual Test Script Run` project toggle. Confirm it turns green/
       checked immediately (no page reload needed).
2. [ ] Log in as `tester1` (same browser or a private window) — confirm
       the Projects page now shows exactly `Manual Test Script Run` and
       nothing else, and that opening it works normally (Dashboard,
       Test Suites, etc. all load).
3. [ ] **(ADMIN)** Back on the **Users** page, click the same project
       toggle again to revoke `tester1`'s access. Confirm it turns off
       immediately.
4. [ ] As `tester1` (same still-logged-in session, no re-login), refresh
       the Projects page — confirm the project has disappeared, and
       that navigating directly to its URL (e.g. `/manual-test-script-run/dashboard`)
       is rejected (403), not silently shown.
5. [ ] **(ADMIN)** Grant `viewer1` access to the same project the same
       way, and confirm `viewer1` can see and read it (Dashboard,
       Reports, etc.) but none of the write actions (see the Viewer
       Guide's "What you cannot do" list).
3. [ ] From the project card, **Archive** the project — confirm it
       requires you to re-enter your own password, and that after
       archiving it either disappears from the default list or shows
       an archived indicator.
4. [ ] **Unarchive** it the same way, confirm it's back to normal.
5. [ ] **(API)** Confirm `DELETE /api/projects/{slug}` requires the
       password-confirmation body and genuinely removes the project —
       do this on a disposable second test project, not the one you'll
       use for the rest of this script.

---

## 3. Test suite authoring

As **(TESTER)** (or ADMIN — testers can do everything up to publish).

1. [ ] **Test Suites** tab → **New Suite** → name it (e.g. `Manual
       Script Suite`), pick a type (REGRESSION/UAT/SMOKE/
       INTEGRATION/OTHER).
2. [ ] Open the suite → **New Draft Revision** → label it `v1`.
3. [ ] **+ Add Case** → fill in checkpoint code, title, setup/action/
       validation/expected result, priority, mutation level. Add at
       least 3 cases, including one `P0` case (needed later for
       go-live readiness testing).
4. [ ] **Import Excel/CSV**: download the **Import Template** first.
       Fill it out matching the column headers exactly, then upload
       it. Confirm the imported cases appear in the case list.
5. [ ] Deliberately break the import: change a column header, upload
       it again — confirm it's rejected with a specific list of
       missing/unexpected columns, not a silent partial import.
6. [ ] **(ADMIN only)** Click **Publish** on the `v1` revision —
       confirm a TESTER account cannot see/use a Publish button (or
       gets a permission error if called directly via API).
7. [ ] Confirm the published revision is now immutable — try editing a
       case, confirm it's rejected or the edit controls are gone.
8. [ ] **Clone for Correction** on the published revision → confirm it
       creates a new `DRAFT` revision with the same case set, editable
       again.
9. [ ] Edit a case in the new draft (change its title to something
       recognizable, e.g. add `CHANGED` to the title) — used later for
       Revision Comparison. Publish this second revision too
       (**(ADMIN)**) once ready — label it `v2`.

---

## 4. Test cycles

1. [ ] **Test Cycles** tab → **New Cycle** → pick the suite, then the
       **published** `v1` revision (confirm draft revisions do NOT
       appear in this dropdown). Name it, pick an environment (e.g.
       `staging`).
2. [ ] Confirm every case in `v1` now shows as a `NOT_RUN` result in
       the cycle.
3. [ ] Edit the suite's `v1` case titles afterward (if still possible)
       or add a new case to `v1` — confirm the already-created cycle's
       snapshot does NOT change (immutable snapshot).
4. [ ] **(ADMIN)** Open the cycle → **Lock Cycle**. Confirm no result/
       evidence can be changed while locked, and the UI tells you to
       ask an admin to reopen it.
5. [ ] **(ADMIN)** **Reopen** the locked cycle — confirm it requires
       typing a reason, and that this shows up later in Recent
       Activity / the activity log.
6. [ ] **Rerun** the cycle from the Dashboard's **Start Testing →
       Rerun Previous Cycle** flow — try both "Entire cycle" and
       "FAIL and BLOCKED cases only" modes (you'll need at least one
       FAIL result first — do this after Section 6).

---

## 5. Quick Manual Test (the fast path)

This is the primary "how fast can a tester start testing" flow —
timed against a **< 30 second** requirement.

1. [ ] Dashboard → **Start Testing** → **Quick Manual Test**.
2. [ ] Fill in a title (e.g. `Login works with valid credentials`),
       optionally an expected result, leave "Evidence required for
       PASS" checked.
3. [ ] Click **Start Test** — time yourself from clicking **Start
       Testing** to landing on an active execution screen with
       **Actual Result**/evidence controls visible. Confirm it's under
       30 seconds (it should take a handful of clicks and a few
       seconds).
4. [ ] Confirm a new system-generated cycle (name starting `Quick
       Test:`) was created behind the scenes and one `NOT_RUN` result
       is now active on screen, ready to execute.

---

## 6. Executing a case

Use the cycle from Section 4 (or the Quick Manual Test result from
Section 5).

1. [ ] Select a case from the left panel. Confirm the script (setup/
       action/expected result) and an evidence/result editor appear on
       the right.
2. [ ] Try clicking **PASS** with no evidence attached — confirm it's
       **rejected** with a visible banner (not silently ignored) when
       the cycle requires evidence for PASS.
3. [ ] Attach evidence three ways, confirming each works:
       - [ ] **Upload file** — pick an image from disk.
       - [ ] **Click here then Ctrl+V to paste** — screenshot
             something, paste it into the box.
       - [ ] **Capture screen** — use the browser's screen-share
             picker, confirm exactly one still frame is captured (no
             video).
4. [ ] Click a thumbnail to open the annotator. Try each tool: arrow,
       rectangle, highlight, freehand, text, numbered callout, and
       blur/redaction. **Save annotation revision** — confirm the
       original screenshot is untouched and a new revision is added on
       top (both viewable).
5. [ ] Fill in **Actual Result**, click **PASS** — confirm it's now
       accepted (evidence present) and the save state indicator
       updates.
6. [ ] On a second case: leave **Actual Result** blank and click
       **NG** (FAIL) — confirm it's rejected until Actual Result is
       filled in. Fill it in, click NG again — confirm it's accepted.
7. [ ] On a third case: click **BLOCKED** without a Blocked Reason —
       confirm rejection; fill in the reason, retry — confirm success.
8. [ ] On a fourth case (ideally not P0): click **N/A** without an N/A
       Reason — confirm rejection; fill in the reason, retry — confirm
       it's accepted but shows an `UNREVIEWED` review status (see
       Section 7).
9. [ ] **Show history** on any case you just changed — confirm every
       prior status/result change is listed with who changed it and
       when, nothing overwritten silently.
10. [ ] Try executing a case in the **locked** cycle from Section 4
        step 4 (before reopening) — confirm it's blocked.

---

## 7. N/A review

1. [ ] **(ADMIN)** Open the case marked N/A in Section 6 step 8.
       Confirm you can **Accept** or **Request changes** on it.
2. [ ] Before reviewing it, check the Dashboard's pass rate and
       go-live readiness — confirm the unreviewed N/A still counts
       against the pass-rate denominator, and (if that case is P0)
       shows as a go-live blocker.
3. [ ] Click **Accept** — confirm the review status changes to
       `ACCEPTED` and, if it was a go-live blocker, the blocker clears
       from the Dashboard/Go-Live Readiness report.
4. [ ] On a different N/A result, click **Request changes** instead —
       confirm the status becomes `CHANGES_REQUESTED` and it's still
       flagged as needing attention.

---

## 8. Defects (API-only today)

1. [ ] **(TESTER/ADMIN, API)** Create a defect against the FAIL result
       from Section 6:
       ```bash
       curl -b cookies.txt -X POST http://127.0.0.1:8000/api/{slug}/defects \
         -H "Content-Type: application/json" \
         -d '{"title":"Login button unresponsive","cycle_id":<id>,"cycle_test_result_id":<id>,"severity":"P1","description_md":"Steps to reproduce..."}'
       ```
2. [ ] Confirm the defect now appears in the **NG and Defect Report**
       (Section 11) and in the Dashboard's "Open Defects by Severity"
       tile.
3. [ ] **(API)** Update the defect's status (`PUT /api/{slug}/defects/
       {id}`) to a closed/resolved state — confirm it drops out of
       "open defects" counts and, if it was P0/P1, any go-live blocker
       tied to it clears.

---

## 9. Sign-offs (API-only today)

1. [ ] **(ADMIN, API)** Record a sign-off:
       ```bash
       curl -b cookies.txt -X POST http://127.0.0.1:8000/api/{slug}/cycles/{cycle_id}/signoffs \
         -H "Content-Type: application/json" \
         -d '{"cycle_id":<id>,"signoff_type":"QA_REVIEW","decision":"APPROVED","comment_md":"Looks good"}'
       ```
       Valid `signoff_type`: `QA_REVIEW`, `BUSINESS_ACCEPTANCE`,
       `GO_LIVE`. Valid `decision`: `APPROVED`, `REJECTED`, `PENDING`.
2. [ ] Record a second sign-off of a different type/decision.
3. [ ] Confirm both appear, in order, in the **Audit/Sign-off Summary**
       report (Section 11) and are never edited in place — each
       decision is its own permanent row.

---

## 10. Dashboard

1. [ ] Open the project Dashboard. Confirm every tile is populated and
       correct against what you did above: Total Cases, PASS/NG/
       Blocked/Not Run/N-A counts, Pass Rate %, Evidence Completeness
       %.
2. [ ] Hover the Pass Rate and Evidence Completeness tiles — confirm a
       tooltip shows the exact formula used.
3. [ ] Confirm the Go-Live Readiness card shows READY or NOT READY
       correctly given your P0 case's status and any open P0/P1
       defects, with a specific, readable blocker list when NOT READY.
4. [ ] Confirm Open Defects by Severity and Pending N/A Reviews counts
       match what you created in Sections 7–8.
5. [ ] Confirm Storage Usage shows a real percentage and GB figure
       (not zero, since you uploaded evidence).
6. [ ] Confirm Recent Activity lists real entries for actions you just
       took (status changes, cycle reopen, etc.) with who and when.
7. [ ] **Continue Last Test** button — confirm it appears after your
       Quick Manual Test and navigates straight back into that
       specific result.

---

## 11. Reports (redesigned — verify the visual redesign specifically)

This section is the direct check for the Reports page redesign: every
report should render as a **visual summary by default** (KPI cards,
badges, progress bars, tables, timelines, or blocker lists) — **never**
a raw JSON dump on first load. Do this as each of ADMIN, TESTER, and
VIEWER at least once (VIEWER should see identical report content,
read-only).

General checks to repeat for **every** report type below:
- [ ] Selecting the report type and clicking **Run Report** loads
      *only* that report (Network tab: exactly one new report request
      fires, not all ten).
- [ ] A one-line description of what the report is for appears under
      the picker.
- [ ] No raw `{...}` JSON is visible anywhere on the page by default.
- [ ] A **"Show Developer Data"** link/button is present at the bottom
      of the report. Clicking it reveals the exact raw JSON API
      response in a collapsed panel; clicking **"Hide Developer
      Data"** collapses it again.

Per-report checks:

1. [ ] **Execution Summary** — cycle name/status/environment header,
       five result-count tiles (Not Run/Pass/NG/Blocked/N-A), Pass
       Rate and Evidence Completeness as progress bars with percent,
       numerator/denominator, and formula text. Numbers match the
       Dashboard for the same cycle.
2. [ ] **Detailed Test Results** — one row per case, status shown as a
       colored badge (not plain text), evidence count column correct.
3. [ ] **NG and Defect Report** — two tables: NG Cases (your Section 6
       FAIL case) and Defects (your Section 8 defect, with a severity
       badge).
4. [ ] **Evidence Completeness** — progress bar + percent, and a
       "Missing Evidence" list of checkpoint codes for any executed
       case with no evidence (should be empty if you attached evidence
       everywhere; if not, confirm the codes listed are correct).
5. [ ] **Revision Comparison** — pick the suite, Revision A = `v1`,
       Revision B = `v2` from Section 3. Confirm four colored groups:
       Added, Removed, Changed (your edited case should show here),
       Unchanged — each showing real checkpoint codes as small badges,
       not a wall of JSON.
6. [ ] **Cycle-to-Cycle Comparison** — pick two different cycles (Cycle
       A defaults to the first cycle; explicitly pick Cycle B). Confirm
       a table with From → To status badges per checkpoint, and rows
       that actually changed are visually highlighted.
7. [ ] **Tester Progress** — one card per tester (you, from Section 6)
       showing total executed and a badge+count per status.
8. [ ] **Go-Live Readiness** — same READY/NOT READY card and blocker
       list style as the Dashboard, with the formula shown underneath.
9. [ ] **Audit/Sign-off Summary** — your two Section 9 sign-offs shown
       as a timeline, each with a decision badge, actor, and
       timestamp, in order.
10. [ ] **Project Storage Usage** — progress bar with GB used / GB
        quota and the configured warning thresholds; if you're near/over
        quota, a red warning banner appears.

---

## 12. Excel and ZIP export

1. [ ] On the Reports page with a cycle selected, click **Export
       Excel** — confirm a `.xlsx` file downloads and opens correctly
       in Excel/LibreOffice/Google Sheets with these 7 sheets: Cover,
       Execution Summary, Test Results, NG/Defects, Evidence Index,
       Revision History, Sign-Off. Numbers match what you saw in the
       app.
2. [ ] Click **Export ZIP Package** — confirm a `.zip` downloads
       containing the same workbook, every evidence image you
       uploaded, and a `manifest.json` with checksums. Open a couple of
       the evidence images from the ZIP and confirm they match what
       you uploaded.
3. [ ] Archive one evidence item (from the case execution screen) and
       re-export the ZIP — confirm the archived item is still included
       and marked `"status":"ARCHIVED"` in the manifest (not silently
       dropped).
4. [ ] **(VIEWER)** Confirm both export buttons work for a VIEWER too
       (exports are read-only operations).
5. [ ] Log out entirely (clear cookies) and try hitting the export URL
       directly — confirm a plain 401, not a file.

---

## 13. Storage quota (ADMIN)

1. [ ] **(API)** `GET /api/projects/{slug}/storage-quota` — note the
       current quota and thresholds.
2. [ ] **(API)** `PUT` a very small quota (e.g. a few KB) —
       `{"storage_quota_bytes": 5000, "storage_warning_thresholds":
       [70,85,95,100]}`.
3. [ ] Try uploading a normal-sized evidence file — confirm it's
       **hard-blocked** with a clear over-quota message.
4. [ ] Restore a sane quota afterward and confirm uploads work again.
5. [ ] Confirm the Dashboard's storage tile and the Project Storage
       Usage report both reflect the near/over-quota state accurately
       while the small quota was in effect.

---

## 14. User management (ADMIN, API)

Already partly covered in Section 1. Additionally:

1. [ ] `GET /api/auth/users` as a non-admin — confirm it's rejected.
2. [ ] Create a user with a duplicate email — confirm a clear
       conflict error, not a silent duplicate.
3. [ ] Confirm a newly created user is forced through the
       password-change flow on first login (already checked in
       Section 1, re-confirm with this new one).

---

## 15. Hybrid runner installation

Do this once before Sections 16–21.

1. [ ] `cd runner && npm install`.
2. [ ] `npx playwright install chromium`.
3. [ ] **(ADMIN)** Runners page (`/runners`) → **Register Runner** →
       give it a label. Confirm the raw token is shown exactly once
       and copied down — refreshing the page never shows it again.
4. [ ] Create `runner/.env` (never commit it) with `BACKEND_BASE_URL`,
       `PROJECT_SLUG` (your test project's slug), `RUNNER_TOKEN` (from
       step 3), `TARGET_BASE_URL`, `TARGET_EMAIL`, `TARGET_PASSWORD`.
5. [ ] Confirm the Runners page shows this token's status as `OFFLINE`
       initially, moving to `ONLINE` once you make a real call with it
       (Section 18).

---

## 16. Workflow authoring (HYB-1)

1. [ ] **Workflows** tab → create a new workflow (name it e.g. `Manual
       Script Workflow`).
2. [ ] Inside it, **New Draft Revision** → label `v1`.
3. [ ] **+ Add Step** several times, covering a realistic sequence,
       e.g.:
       - `NAVIGATE` to `/login`
       - `FILL` the email field (`ROLE` or `LABEL` locator strategy)
       - `FILL` the password field, checking **Sensitive**, using a
         `${TEST_PASSWORD}` placeholder value (never a literal
         password)
       - `CLICK` the Sign in button
       - a `MANUAL_CHECKPOINT` step with real checkpoint instructions
         (e.g. "Confirm the Projects page loaded correctly")
       - `ASSERT_TEXT` or `ASSERT_URL` after the checkpoint
4. [ ] Reorder two steps using the ↑/↓ controls — confirm the order
       persists after a page refresh.
5. [ ] Delete one step, confirm it's removed.
6. [ ] **Linked Test Cases** — link one of your Section 3 test cases
       to this revision.
7. [ ] **(ADMIN)** **Publish** the revision — confirm a TESTER cannot
       publish, and that steps are no longer editable once published.
8. [ ] **Clone for correction** on the published revision — confirm it
       creates a new editable draft with the same steps.

---

## 17. Recording session — Playwright mode (HYB-3)

1. [ ] In `runner/`, run `npm run record` (needs `RUNNER_TOKEN` set,
       and `RECORDER_DEBUG_PORT`/headless are optional).
2. [ ] On the Workflow Detail page, under **Record a Workflow**, enter
       a starting URL and click **Start Recording**.
3. [ ] Confirm a **real, separate headed Chromium window** opens
       (this is the runner's own browser, not your normal browser).
4. [ ] Interact with the target app in that window: click something,
       fill a field, navigate to another page. Confirm each action
       appears live in the **Captured Steps** list in QA-Again's UI
       within a couple of seconds.
5. [ ] Fill in a password-type field in the recorded browser — confirm
       the captured step shows `sensitive` and does **not** display
       the real value anywhere in the UI.
6. [ ] **Pause Recording** — interact with the browser window again —
       confirm nothing new is captured while paused.
7. [ ] **Resume Recording** — confirm capturing resumes.
8. [ ] **Undo last action** — confirm exactly the most recent step
       disappears from the list; call it twice more, confirm it keeps
       walking backward one step at a time.
9. [ ] **+ Insert Checkpoint** — type an instruction, confirm a
       `MANUAL_CHECKPOINT` step appears in the captured list at the
       current position.
10. [ ] **Stop Recording** — confirm the Chromium window this session
        opened closes itself and the panel moves to review mode
        (reorder/delete/edit still available, "Test locator" button on
        steps with a locator).
11. [ ] Click **Test locator** on a captured step — confirm it reports
        a match count against the real page (requires the recording
        browser... note: if the browser already closed on Stop, confirm
        this correctly reports failure/unavailable rather than lying
        about a match).
12. [ ] For the sensitive step, set its Variable Name field to
        `${TEST_PASSWORD}` — confirm it saves.
13. [ ] **Save as Draft Revision** — label it, confirm a new `DRAFT`
        workflow revision appears with these exact steps as real
        `WorkflowStep` rows.
14. [ ] Start a second recording session and click **Discard** instead
        — confirm the buffer is deleted and no draft revision is
        created.
15. [ ] **After every recording session above (started, stopped,
        discarded, or left running), confirm zero leftover Chromium
        processes/profile directories remain** — see
        [Section 22](#22-browser-process-cleanup-acceptance-check).

---

## 18. Recording session — Chrome Extension mode (ADR-HYB-002)

1. [ ] Load the unpacked extension from `extension/` into Chrome
       (`chrome://extensions` → Developer mode → Load unpacked).
2. [ ] Open your target app in one tab, and QA-Again in another. On
       the Workflow Detail page, start a recording session — leave it
       at `REQUESTED` (don't run `npm run record` this time).
3. [ ] Click **Authorize Extension** — confirm a short-lived **pairing
       code** is shown exactly once, with 3-step paste instructions.
4. [ ] Click the QA-Again Recorder extension icon while your target
       tab is active. Paste the pairing code from step 3 into the one
       text box and click **Start Recording on This Tab** — confirm
       the session's status moves to `RECORDING` in QA-Again's own UI
       (polling picks it up), and that a real Chrome permission prompt
       appeared naming the correct backend origin.
5. [ ] Confirm the **Advanced** fallback still works: expand it, fill
       in backend URL / project slug / session ID / token by hand
       (from a fresh Authorize Extension call on a new session), and
       confirm Start Recording connects the same way.
6. [ ] Confirm a garbled/partial pairing code is rejected with a clear
       "Pairing code is not valid" message rather than a silent
       failure or a raw JS error.
7. [ ] Interact with the target tab normally (no separate Playwright
       browser this time — it's your own tab). Confirm captured steps
       appear in QA-Again's Captured Steps list.
8. [ ] Fill a password field on the target tab — confirm it's captured
       as `sensitive` with no real value, exactly like Playwright mode.
9. [ ] Use **Undo last action** from the extension popup — confirm it
       removes the step (same effect as the QA-Again UI's own Undo).
10. [ ] **Pause**/**Resume** from the extension popup — confirm the
        QA-Again UI reflects the state change.
11. [ ] **Stop** from the extension popup — confirm the session status
        moves to `STOPPED` and the extension's authorization is
        revoked (a repeat call using the same token should now fail).
12. [ ] Review and **Save as Draft Revision** exactly as in Section 17
        — confirm it works identically regardless of which capture
        mode produced the steps.
13. [ ] Confirm the extension never requested/used a
        `host_permissions` prompt beyond what's declared in its
        manifest, and that closing the browser entirely clears its
        stored session token (`chrome.storage.session`, not
        `chrome.storage.local` — check via
        `chrome://extensions` → Inspect views → Application →
        Storage after restarting Chrome).

---

## 19. Job execution and manual checkpoints (HYB-2 / HYB-4)

1. [ ] With a **published** workflow revision (from Section 16 or 17),
       on the Workflow Detail page click **Queue Run**.
2. [ ] Run `npm run execute` in `runner/` (or leave a long-lived runner
       loop going, per your setup) — confirm it claims the queued run.
3. [ ] Confirm a **real headed Chromium window** opens and the steps
       execute one by one, visible in the Runs list (`QUEUED` →
       `CLAIMED`/`STARTING` → `RUNNING`), each step showing
       PASSED/FAILED with locator/failure details on failure.
4. [ ] When the run reaches your `MANUAL_CHECKPOINT` step, confirm:
       - [ ] The run's status becomes `WAITING_FOR_HUMAN`.
       - [ ] The **Manual Checkpoint** panel shows your checkpoint
             instructions, expected value (if set), any linked Track A
             test case, prior automated step results, and a real
             screenshot the runner captured.
       - [ ] An elapsed "waiting Xs/Xm" counter ticks up live.
5. [ ] Submit a **PASS** decision (with an optional actual result) —
       confirm the *same* Chromium window/session resumes (not a fresh
       relaunch) and remaining steps execute in it.
6. [ ] On a second run, reach the checkpoint again and submit **FAIL**
       with a required actual result — confirm the run terminates
       immediately as `FAILED` and does **not** attempt to resume.
7. [ ] On a third run, submit **BLOCKED** or **NOT_APPLICABLE** with a
       required reason — confirm the same terminal behavior, and that
       a `NOT_APPLICABLE` checkpoint decision enters the same
       admin-review queue as Track A's own N/A review (Section 7).
8. [ ] While a run is `RUNNING` (not yet at a checkpoint), click
       **Cancel** — confirm it stops cleanly and the run's final
       status reflects cancellation.
9. [ ] From the checkpoint panel, create a new defect and link it —
       confirm it shows up both there and in the project's defect
       list/NG-Defect report.
10. [ ] Kill the runner process (Ctrl+C) while a run is mid-execution
        (not at a checkpoint) — confirm the run eventually reports
        `RUNNER_LOST` (may take up to the lease-expiry window) rather
        than hanging forever or silently showing success.
11. [ ] **After every run above (passed, failed, blocked, cancelled,
        or runner-lost), confirm zero leftover Chromium
        processes/profile directories remain** — see
        [Section 22](#22-browser-process-cleanup-acceptance-check).

---

## 20. Runner token management

1. [ ] Runners page — confirm your Section 15 token shows `ONLINE`
       after the activity in Sections 17–19 (any authenticated call
       counts as a heartbeat), and its "Last heartbeat" timestamp is
       recent.
2. [ ] **Revoke** the token — confirm you're prompted to confirm, and
       that the runner process's next call is rejected.
3. [ ] Confirm a non-admin cannot reach the Runners page at all (should
       show "Runner management is ADMIN-only" or be inaccessible).

---

## 21. Hybrid reports and timing (HYB-5)

1. [ ] **Hybrid Reports** tab (separate from the Track A Reports page
       — confirm it's a genuinely separate screen, not the same one).
2. [ ] Confirm the hybrid dashboard shows: run-status counts, machine
       vs. human provenance (structurally distinct — automated step
       outcomes vs. human checkpoint decisions never blended into one
       count), runner reliability, retry/runner-lost frequency,
       checkpoint-waiting summary, evidence completeness, defect
       linkage, and recent activity — all reflecting the runs you did
       in Section 19.
3. [ ] Check locator-failures, failure-categories, frequent-failures,
       and slowest-steps sub-views — confirm they show real data if
       you had any failing steps, or an honest empty state if not.
4. [ ] Open the timing view for one of your completed runs — confirm
       it breaks down queue delay, browser startup, per-step
       durations, and any manual-checkpoint waiting time, and that the
       numbers are plausible (not zero/negative).
5. [ ] Re-export the Track A cycle's Excel workbook for a cycle linked
       to hybrid runs — confirm the 8 additional hybrid sheets appear
       (Workflow Definitions/Revisions/Steps/Runs, Step Results,
       Checkpoint Decisions, Runner Activity, Timing Trends) alongside
       the original 7 Track A sheets, unchanged.
6. [ ] Re-export the ZIP — confirm `manifest.json` has a `hybrid` key
       linking every hybrid entity by id, and hybrid evidence
       (e.g. checkpoint screenshots) is included and checksum-correct.

---

## 22. Browser process cleanup acceptance check

This validates the headed-Chrome leak fix directly (see
[docs/hybrid/BROWSER_CLEANUP.md](hybrid/BROWSER_CLEANUP.md) for the
full root-cause writeup). Do this on Windows using Task Manager (or
`Get-Process chrome`), and on macOS/Linux using Activity
Monitor/`ps`.

1. [ ] **Before** starting any recording/run in Sections 17–19, note
       there are zero Chrome/Chromium windows whose title/profile
       looks runner-owned (a `qa-again-playwright-*` profile
       directory — check via
       `Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" |
       Select CommandLine` on Windows, or `ps aux | grep
       qa-again-playwright` on macOS/Linux).
2. [ ] **Successful run**: run a recording session and a workflow run
       through to a clean finish. Immediately after, confirm zero
       `qa-again-playwright-*` Chrome processes remain and no leftover
       `qa-again-playwright-*` temp profile folder remains on disk.
3. [ ] **Deliberately failing run**: queue a run against a workflow
       step with a locator you know won't match (e.g. a bogus
       `data-testid`), let it fail. Confirm zero leftover
       `qa-again-playwright-*` processes/profiles remain afterward.
4. [ ] **Cancelled/timeout run**: queue a run, cancel it mid-flight
       (Section 19 step 8), or let a step legitimately time out.
       Confirm zero leftover processes/profiles remain afterward.
5. [ ] **Kill the runner process directly** (Ctrl+C in its terminal,
       or Task Manager "End task") while a browser is open (recording
       or mid-run, not at a checkpoint). Confirm the browser window
       also closes (via the runner's signal handler) — if it doesn't
       close instantly, confirm it's gone within a few seconds and
       there's no orphaned process left five minutes later.
6. [ ] Run the automated acceptance script yourself for a fast,
       repeatable version of checks 2–4:
       ```bash
       cd runner
       node scripts/verify-browser-cleanup.mjs
       ```
       Confirm it prints `ALL BROWSER CLEANUP ACCEPTANCE CHECKS
       PASSED`.
7. [ ] If any orphaned process is ever found, confirm the operator
       cleanup scripts find and (only when asked) remove **just**
       that process — never your own everyday Chrome:
       ```powershell
       # Windows — list only, safe by default
       .\runner\scripts\cleanup-qa-again-browsers.ps1
       # Windows — actually clean up
       .\runner\scripts\cleanup-qa-again-browsers.ps1 -Kill
       ```
       ```bash
       # macOS/Linux
       ./runner/scripts/cleanup-qa-again-browsers.sh
       ./runner/scripts/cleanup-qa-again-browsers.sh --kill
       ```
       Confirm the read-only listing never includes a Chrome process
       you know is your own regular browsing session.

---

## 23. Role-based access — cross-cutting recheck

Do a final pass confirming role enforcement holds everywhere you
touched above, as **(VIEWER)**:

1. [ ] Every "create/edit/delete/status-change" button (New Suite, New
       Cycle, PASS/NG/Blocked/N-A, uploading evidence, annotating,
       archiving evidence, creating a defect, recording a sign-off,
       lock/reopen a cycle, publish, queue a run, submit a checkpoint
       decision) is either hidden or returns a real permission error
       if you call the endpoint directly.
2. [ ] Dashboard, Reports (both Track A and Hybrid), Excel/ZIP export,
       and read-only browsing of suites/cycles/workflows all work
       identically to what ADMIN/TESTER see.
3. [ ] The Runners page correctly refuses VIEWER (and TESTER) access.

---

## Sign-off

Record the following once you've worked through every section above:

- **Tester name:**
- **Date:**
- **Environment tested** (local / staging / production URL):
- **Commit hash tested** (`git rev-parse HEAD`):
- **Sections fully passed:**
- **Sections with findings** (list section number + what happened
  instead of the expected result):
- **Defects filed as a result of this run** (link/IDs):
- **Overall verdict:** PASS / FAIL / PASS WITH KNOWN ISSUES

This sign-off is itself real evidence — consider recording it as a
`QA_REVIEW` or `GO_LIVE` sign-off (Section 9) against a representative
cycle, so it's part of the project's own permanent audit trail, not
just this document.
