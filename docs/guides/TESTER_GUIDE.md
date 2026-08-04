# QA-Again — Tester Guide

TESTER is the day-to-day execution role: author test content, run
cycles, capture evidence.

## Sign in

Same as any user — sign in, set a new password on first login if asked.

## Project access

You only see and can act on projects an admin has explicitly assigned
to you (Projects page shows just those). If a project you expect is
missing, ask an admin to grant it on the **Users** page — nothing is
automatic, even for a project you'd normally be the one working in. You
also can't create a new project yourself (ADMIN-only) — ask an admin to
create it, then assign you to it.

## Authoring a test suite

1. **Test Suites** tab → **New Suite** (name + type: REGRESSION/UAT/
   SMOKE/INTEGRATION/OTHER).
2. Open the suite → **New Draft Revision** (give it a label like `v1`).
3. Inside the revision, either:
   - **+ Add Case** and fill in the form (checkpoint code, title,
     setup/action/validation/expected result, priority, mutation level),
     or
   - **Import Excel/CSV** — download the **Import Template** first, fill
     it in exactly matching the column headers (the import is strict —
     mismatched headers are rejected with a list of what's missing/
     unexpected, not silently guessed at), then upload it.
4. When the case list is complete, click **Publish**. **Published
   revisions are immutable** — you cannot edit a case afterward. If you
   need to fix something post-publish, use **Clone for Correction**,
   which copies the whole case set into a new draft revision for you to
   edit and re-publish.

## Running a cycle

1. **Test Cycles** tab → **New Cycle**. Pick the suite, then a
   **published** revision (drafts won't appear in that dropdown — you
   must publish first), give it a name and environment.
2. This snapshots every case in that revision as a `NOT_RUN` result —
   later edits to the suite never change this cycle.
3. Open the cycle to reach the execution screen: a case list on the
   left (filterable by status), the selected case's script and an
   evidence/result editor on the right.

## Executing a case

1. Select a case from the left panel.
2. Capture evidence **before** marking PASS — the app enforces "no PASS
   without evidence" by default (configurable per cycle by an admin).
   Three ways to add evidence:
   - **Upload file** — pick an image from disk.
   - **Click here then Ctrl+V to paste** — take a screenshot with your
     OS's tool, then paste it directly into that box.
   - **Capture screen** — uses your browser's screen-share picker to
     grab a single frame (no video, ever).
3. Click a thumbnail to open the annotator: arrow, rectangle, highlight,
   freehand, text, numbered callout, and blur/redaction tools, orange by
   default. **Save annotation revision** — this never overwrites the
   original screenshot, it adds a new revision on top.
4. Fill in **Actual Result** (required for NG), **Blocked Reason**
   (required for Blocked), or **N/A Reason** (required for N/A — an
   admin must also approve an N/A before it stops counting against the
   pass rate).
5. Click **PASS**, **NG**, **BLOCKED**, or **N/A**. The save state shows
   next to the buttons; a validation error (e.g. missing evidence, missing
   reason) shows as a banner at the top, not silently.
6. **Show history** on any case reveals every prior status/result change
   with who changed it and when — nothing is silently overwritten.

## Locked cycles

Once an admin locks a cycle, you can't change any result or evidence in
it — the UI will tell you to ask an admin to reopen it (which requires
them to give a reason, and is itself audited).

## Reporting a defect

**Test Suites → suite → revision** doesn't have a defect button — go to
the cycle's Reports page, or use the API directly (`POST /api/{slug}/
defects`) with the cycle/result and a severity (P0–P3). A future UI
convenience for this may be added; for now it's reachable via the API
while the app is this young.

## Exporting

**Reports** page → pick a cycle → **Export Excel** (7-sheet workbook:
cover, execution summary, detailed results, NG/defects, evidence index,
revision history, sign-off) or **Export ZIP Package** (the same workbook
plus every evidence image plus a manifest with checksums, as a portable
archive).
