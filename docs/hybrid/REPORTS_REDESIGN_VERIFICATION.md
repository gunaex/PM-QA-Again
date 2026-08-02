# Reports Redesign — Real-Browser Verification

Verifies commit `7369038` (Reports visual redesign) per
[docs/MANUAL_TEST_SCRIPT.md](../MANUAL_TEST_SCRIPT.md) Section 11, using
a real headed Chromium instance driven end-to-end against a real,
isolated backend/frontend pair (not mocked). Not the human sign-off
called for in the manual test script — that's still outstanding — but a
real-browser functional pass confirming the redesign works before a
human walks through it.

## Environment

- Isolated backend (`uvicorn`, fresh SQLite `DATA_DIR`) on
  `127.0.0.1:8010`, isolated frontend (`vite`) on `127.0.0.1:5180`,
  both real dev servers, no mocking. Kept off the user's normal
  `8000`/`5173` dev instance so this run touches no real project data.
- Browser launched via `runner/scripts/lib/browserLifecycle.mjs`
  (`launchTrackedBrowser`) — the same tracked-lifecycle helper the
  browser-cleanup fix added, so this run doubles as another real
  exercise of that fix.
- Seed data: one project, one suite with two published revisions (`v1`,
  `v2`, differing by one added/removed/changed case — for Revision
  Comparison), two cycles (one with a PASS + a FAIL + a linked P1
  defect + a QA_REVIEW sign-off; a second with a single PASS — for
  Cycle-to-Cycle Comparison), all created via the real HTTP API.

## Finding and fix

Initial run of the verification script crashed the app: switching the
**Report** dropdown to a new type *before* clicking **Run Report**
left stale data from the previous report type in state, and the new
redesign's per-type renderers (`renderReportBody`) assumed `data`
always matched the current `reportType`. `DetailedResultsView` (and
others) called `DataTable` with a non-array object, which does
`Object.keys(rows[0])` — `rows[0]` on a non-array is `undefined`,
throwing and blanking the whole page (no error boundary). This is a
real regression introduced by the redesign, not a test artifact — the
old raw-JSON fallback degraded gracefully here since it branched on
`Array.isArray(data)` rather than on `reportType`.

**Fix**: `frontend/src/pages/ReportsPage.jsx` — the report-type
`<select>`'s `onChange` now also clears `data`/`error`
(`setData(null); setError(null)`) alongside `setReportType(...)`, so a
type change always hides the previous report until **Run Report** is
clicked again for the new type. Verified fixed by rerunning the full
script below afterward with zero crashes across all 10 types, repeated
type switches, and picker changes.

(Separately: two `/auth/me` 401s from the pre-login probe, and initial
cross-origin cookie/CORS setup mistakes in the verification harness
itself — using `localhost` for the frontend against a `127.0.0.1`
backend broke `SameSite=Lax` cookie delivery — were verification-
environment issues, not application bugs, and are not reflected in the
checklist below.)

## Automated real-browser pass (this session)

Script: `runner/scripts/_verify-reports-manual.mjs` (scratch, not
committed — logic is now covered by this document and by
`docs/MANUAL_TEST_SCRIPT.md` Section 11 for repeatable human execution).

| # | Report | Loads w/o error | Description shown | Visual (not raw JSON) by default | Dev Data toggle present & works | Exactly 1 report request |
|---|---|---|---|---|---|---|
| 1 | Execution Summary | ✅ | ✅ | ✅ | ✅ | ✅ |
| 2 | Detailed Test Results | ✅ | ✅ | ✅ | ✅ | ✅ |
| 3 | NG and Defect Report | ✅ | ✅ | ✅ | ✅ | ✅ |
| 4 | Evidence Completeness | ✅ | ✅ | ✅ | ✅ | ✅ |
| 5 | Revision Comparison | ✅ | ✅ | ✅ | ✅ | ✅ |
| 6 | Cycle-to-Cycle Comparison | ✅ | ✅ | ✅ | ✅ | ✅ |
| 7 | Tester Progress | ✅ | ✅ | ✅ | ✅ | ✅ |
| 8 | Go-Live Readiness | ✅ | ✅ | ✅ | ✅ | ✅ |
| 9 | Audit/Sign-off Summary | ✅ | ✅ | ✅ | ✅ | ✅ |
| 10 | Project Storage Usage | ✅ | ✅ | ✅ | ✅ | ✅ |

For every report, the script recorded the exact network request(s)
fired by clicking **Run Report** — each type fired precisely one
`GET .../reports/<type>` call, confirming only the selected report
loads (no eager fetch of the other nine).

**Console errors observed across the entire run**: exactly two, both
`Failed to load resource: 401` from the expected pre-login `/auth/me`
probe (same as every other verification script and the deployment
smoke-test checklist treat as expected noise). **Zero console errors**
during any report view, toggle, or export.

## Export verification

- **Excel** (`GET .../export/excel`): HTTP 200,
  `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`,
  15,187 bytes. Opened with `openpyxl` — loads without error, 15
  sheets present: `00_Cover`, `01_Execution_Summary`,
  `02_Test_Results`, `03_NG_Defects`, `04_Evidence_Index`,
  `05_Revision_History`, `06_Sign_Off` (the 7 Track A sheets,
  unchanged), plus `Workflow Definitions`, `Workflow Revisions`,
  `Workflow Steps`, `Workflow Runs`, `Step Results`, `Checkpoint
  Decisions`, `Runner Activity`, `Timing Trends` (the 8 hybrid sheets,
  correctly empty since this cycle had no linked hybrid runs).
- **ZIP** (`GET .../export/zip`): HTTP 200, `application/zip`, 14,507
  bytes. `zipfile.testzip()` reports no corrupt members. Contains
  `reports-verify-2_Verify-Cycle.xlsx`, `report.html`,
  `manifest.json`.
- Both downloads were driven by the real `<a href>` export buttons'
  underlying URLs with the real session cookie (matching how the
  browser actually issues them), not a synthetic bypass.

## Screenshots

Representative full-page screenshots captured during this run (not
committed to the repo — available on request):
`execution-summary.png`, `detailed-results.png`, `ng-defects.png`,
`evidence-completeness.png`, `revision-comparison.png`,
`cycle-comparison.png`, `tester-progress.png`,
`go-live-readiness.png`, `signoff-summary.png`, `storage-usage.png`.
Visually confirmed: KPI-card result-count tiles, colored status
badges, green/emerald progress bars with formula captions, a four-
column colored diff view for Revision Comparison (Added/Removed/
Changed/Unchanged), a From→To badge table with amber-highlighted
changed rows for Cycle Comparison, a READY/NOT READY readiness card,
and a collapsed-by-default "Show Developer Data" link that expands to
the exact raw JSON on click.

## Browser-cleanup cross-check

Zero `qa-again-playwright-*` Chrome processes remained after this
entire run (verified via `Win32_Process`), and the tracked-browser
registry directory was empty — another real confirmation of the
browser-cleanup fix (`79ca9cd`), this time exercised by a Reports-page
run rather than a runner/recorder session.

## What this does NOT close

- This is an AI-driven automated real-browser pass, not the human
  sign-off `docs/MANUAL_TEST_SCRIPT.md` calls for. A human should still
  work through Section 11 (and ideally the rest of the script)
  themselves.
- The three human-operated Release Closure checks (real R2 staging
  smoke test, Screen Capture acceptance, clipboard-paste acceptance)
  remain unresolved. **The application is not production-ready**
  regardless of this verification passing.
- This run used a project named `reports-verify-2` on an isolated,
  disposable local instance — no production or shared data was
  touched.
