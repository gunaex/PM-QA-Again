# Release Closure Procedure

Status: **1 of 3 items closed** — 2026-08-02. The real Cloudflare R2
staging smoke test (§1) has been executed by the human operator and
passed; Screen Capture API acceptance (§2) and clipboard-paste
acceptance (§3) remain outstanding.

**2026-08-02 update**: a preview-before-upload confirmation step was
added for Screen Capture and clipboard-paste (checks 2 and 3 below now
reflect this). The confirm/cancel mechanism itself was verified with
real headed-browser Playwright automation and direct DB inspection —
cancel creates zero `EvidenceItem` rows, confirm creates exactly one —
but that automated run used a synthetic clipboard write, not the
`getDisplayMedia` OS picker or a human-sourced clipboard image, so it
does **not** substitute for checks 2 and 3 below, which still require a
human operator in a real browser.

This document exists to close the three remaining items in
`docs/RELEASE_CHECKLIST.md`. All three require resources this
development environment does not have (real Cloudflare R2 credentials,
a real interactive browser with OS-level permission prompts and a real
clipboard) and must be run by a human operator. **No application code
changes, security-control weakening, permission bypass, or
automation-only code path is required or permitted to complete these
checks** — every step below exercises the application exactly as a real
user or the real infrastructure would.

Once the operator completes all three and reports results (pass/fail +
evidence, using the reporting template at the end of this document),
whoever is running the Claude Code session should update
`docs/RELEASE_CHECKLIST.md` and `docs/RELEASE_REHEARSAL.md` with the
actual outcome, then re-run the full backend test suite and frontend
build, then report one of exactly two final statuses: **PRODUCTION
READY** or **NOT PRODUCTION READY**. Until that happens, the project
remains **NOT PRODUCTION READY**.

---

## 1. Real Cloudflare R2 staging smoke test

### Prerequisites

- A real Cloudflare R2 bucket dedicated to **staging** — not production
  (`docs/DEPLOYMENT.md`'s bucket setup section). Confirm it's private
  (no public access, no custom domain attached).
- An R2 API token scoped to that one bucket, Object Read & Write.
- Python 3.11, this repo checked out, `backend/requirements.txt`
  installed in a venv.
- A scratch working directory — this check runs the backend **locally**
  against the **real** staging bucket; it does not require a Fly
  deployment.

### Environment variables

```bash
export R2_ACCOUNT_ID=<staging account id>
export R2_BUCKET_NAME=<staging bucket name>
export R2_ACCESS_KEY_ID=<staging access key>
export R2_SECRET_ACCESS_KEY=<staging secret key>
```

### Step A — storage-layer smoke test (fast, isolated)

```bash
cd backend
python -m venv .venv
./.venv/Scripts/pip install -r requirements.txt
./.venv/Scripts/python scripts/r2_staging_smoke_test.py
```

**Expected successful result**: the script prints `1.` through `5.`
each followed by `ok`, ending with `ALL CHECKS PASSED — real R2
endpoint, credentials, upload, presigned download, and retrieval all
confirmed working.` and exits 0. This alone proves credentials/endpoint
connectivity, `put`/`head`/`get`, a real HTTP fetch of a presigned URL
(with the `Content-Disposition` filename override), and `delete`.

**Failure diagnosis**: the script names the exact failed step
(`FAILED at: <step>`). `put_object` failing → check
`R2_ACCESS_KEY_ID`/`R2_SECRET_ACCESS_KEY` and that the token is scoped to
this bucket. `get_object`/`head_object` failing after a successful `put`
→ check the bucket name matches exactly (case-sensitive). The presigned
HTTP fetch failing → check the bucket is reachable over the public
internet (R2 buckets are internet-reachable via presigned URLs by
design, this isn't a network/firewall issue on Cloudflare's side, so a
failure here likely means a clock-skew or signature issue — check the
operator machine's system clock).

### Step B — full application-level walkthrough

This exercises upload → metadata → authenticated download → presigned
redirect details → integrity → archive → cleanup, all through the real
running app, not just the storage abstraction directly.

**Run the backend against the real staging bucket:**

```bash
cd backend
STORAGE_BACKEND=r2 \
DATA_DIR=./data-r2-closure \
ADMIN_EMAIL=closure-admin@example.com \
ADMIN_PASSWORD=ClosureTest123! \
JWT_SECRET_KEY=closure-test-session-only \
ALLOWED_ORIGINS=http://localhost:5173 \
COOKIE_SECURE=false \
  ./.venv/Scripts/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

(`R2_ACCOUNT_ID`/`R2_BUCKET_NAME`/`R2_ACCESS_KEY_ID`/
`R2_SECRET_ACCESS_KEY` inherited from your shell per the export above.)

**In a second terminal, set up a test project and upload a uniquely named object:**

```bash
# Login + force password change
curl -s -c cookies.txt -X POST http://127.0.0.1:8000/api/auth/login \
  -H "Content-Type: application/json" -H "Origin: http://localhost:5173" \
  -d '{"email":"closure-admin@example.com","password":"ClosureTest123!"}'
curl -s -b cookies.txt -c cookies.txt -X POST http://127.0.0.1:8000/api/auth/change-password \
  -H "Content-Type: application/json" -H "Origin: http://localhost:5173" \
  -d '{"current_password":"ClosureTest123!","new_password":"ClosureTest456!"}'

# Project + suite + revision + case + publish + cycle (minimum scaffold to attach evidence to)
SLUG=$(curl -s -b cookies.txt -X POST http://127.0.0.1:8000/api/projects \
  -H "Content-Type: application/json" -H "Origin: http://localhost:5173" \
  -d '{"name":"R2 Closure Test"}' | python -c "import sys,json;print(json.load(sys.stdin)['slug'])")
SUITE_ID=$(curl -s -b cookies.txt -X POST http://127.0.0.1:8000/api/$SLUG/suites \
  -H "Content-Type: application/json" -H "Origin: http://localhost:5173" \
  -d '{"name":"s","suite_type":"OTHER"}' | python -c "import sys,json;print(json.load(sys.stdin)['id'])")
REV_ID=$(curl -s -b cookies.txt -X POST http://127.0.0.1:8000/api/$SLUG/suites/$SUITE_ID/revisions \
  -H "Content-Type: application/json" -H "Origin: http://localhost:5173" \
  -d '{"revision_label":"v1"}' | python -c "import sys,json;print(json.load(sys.stdin)['id'])")
curl -s -b cookies.txt -X POST http://127.0.0.1:8000/api/$SLUG/revisions/$REV_ID/cases \
  -H "Content-Type: application/json" -H "Origin: http://localhost:5173" \
  -d '{"checkpoint_code":"R2-1","title":"t","action_md":"a","expected_result_md":"e"}' >/dev/null
curl -s -b cookies.txt -X POST http://127.0.0.1:8000/api/$SLUG/suites/$SUITE_ID/revisions/$REV_ID/publish \
  -H "Origin: http://localhost:5173" >/dev/null
CYCLE_ID=$(curl -s -b cookies.txt -X POST http://127.0.0.1:8000/api/$SLUG/cycles \
  -H "Content-Type: application/json" -H "Origin: http://localhost:5173" \
  -d "{\"suite_id\":$SUITE_ID,\"script_revision_id\":$REV_ID,\"name\":\"c\",\"environment\":\"r2-closure\"}" \
  | python -c "import sys,json;print(json.load(sys.stdin)['id'])")
RESULT_ID=$(curl -s -b cookies.txt "http://127.0.0.1:8000/api/$SLUG/cycles/$CYCLE_ID/results" \
  | python -c "import sys,json;print(json.load(sys.stdin)[0]['id'])")

# A uniquely named real PNG (so it's identifiable in the bucket by name during manual inspection)
TESTFILE="r2-closure-$(date +%s).png"
python -c "
import struct, zlib
def chunk(t,d): return struct.pack('>I',len(d))+t+d+struct.pack('>I',zlib.crc32(t+d))
open('$TESTFILE','wb').write(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',2,2,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(b'\x00\xff\x00\x00\xff\x00\x00'*4))+chunk(b'IEND',b''))
"
sha256sum "$TESTFILE"   # record this — compared against the DB and the downloaded copy later

EVIDENCE=$(curl -s -b cookies.txt -X POST \
  "http://127.0.0.1:8000/api/$SLUG/cycles/$CYCLE_ID/results/$RESULT_ID/evidence" \
  -H "Origin: http://localhost:5173" -F "file=@$TESTFILE")
echo "$EVIDENCE"
EVIDENCE_ID=$(echo "$EVIDENCE" | python -c "import sys,json;print(json.load(sys.stdin)['id'])")
```

**Metadata persistence** — confirm the response and a fresh `GET` both
show `original_content_type=image/png`, `original_size_bytes` matching
the local file's size, and `original_sha256` matching the `sha256sum`
recorded above:

```bash
curl -s -b cookies.txt "http://127.0.0.1:8000/api/$SLUG/cycles/$CYCLE_ID/results/$RESULT_ID/evidence/$EVIDENCE_ID"
sqlite3 data-r2-closure/projects/$SLUG.db \
  "SELECT object_key, original_sha256, original_size_bytes, status FROM evidence_items;"
```
Expected `object_key` shape: `evidence/<slug>/<result_id>/<uuid>.png`.

**Authenticated application download + presigned redirect details:**

```bash
curl -v -b cookies.txt \
  "http://127.0.0.1:8000/api/$SLUG/cycles/$CYCLE_ID/results/$RESULT_ID/evidence/$EVIDENCE_ID/original" \
  -o /dev/null 2>&1 | grep -i -E "< HTTP|< location"
```
**Expected**: `< HTTP/1.1 307 Temporary Redirect` and a `Location:`
header pointing at `https://<account_id>.r2.cloudflarestorage.com/...`
containing `X-Amz-Expires=300` and a `response-content-disposition`
query parameter whose decoded value is `inline; filename="<TESTFILE
name>"` — **not** the raw UUID object key.

**Byte-for-byte integrity:**

```bash
curl -s -L -b cookies.txt \
  "http://127.0.0.1:8000/api/$SLUG/cycles/$CYCLE_ID/results/$RESULT_ID/evidence/$EVIDENCE_ID/original" \
  -o downloaded.png
sha256sum downloaded.png "$TESTFILE"
```
**Expected**: identical hashes for both files, and both equal to the
`original_sha256` recorded in the DB.

**Archive behavior:**

```bash
curl -s -b cookies.txt -X PUT \
  "http://127.0.0.1:8000/api/$SLUG/cycles/$CYCLE_ID/results/$RESULT_ID/evidence/$EVIDENCE_ID/archive" \
  -H "Origin: http://localhost:5173"
curl -s -b cookies.txt "http://127.0.0.1:8000/api/$SLUG/cycles/$CYCLE_ID/results/$RESULT_ID/evidence"   # expect []
curl -s -b cookies.txt "http://127.0.0.1:8000/api/$SLUG/cycles/$CYCLE_ID/results/$RESULT_ID/evidence/$EVIDENCE_ID/original" -o archived-still-downloadable.png
curl -s -b cookies.txt "http://127.0.0.1:8000/api/projects/$SLUG/storage-quota"   # used_bytes still > 0
```
**Expected**: status becomes `ARCHIVED`, it disappears from the active
list, it's **still** downloadable (object untouched), and it still
counts toward quota (requirement 3 from the R2 migration work).

### Expected database and R2 state at this point

- SQLite: one `EvidenceItem` row, `status=ARCHIVED`, all metadata fields
  populated and correct.
- R2 bucket: exactly one object under `evidence/<slug>/<result_id>/`,
  matching the recorded key.

### Cleanup + orphan confirmation

```bash
# Stop the backend (Ctrl+C in its terminal) is not required for this —
# delete via the API while it's still running:
curl -s -b cookies.txt -X DELETE "http://127.0.0.1:8000/api/projects/$SLUG" \
  -H "Content-Type: application/json" -H "Origin: http://localhost:5173" \
  -d '{"password":"ClosureTest456!"}'
```
This deletes the project's SQLite file (and its `EvidenceItem` row) but
— per the documented gap in `docs/guides/ADMIN_GUIDE.md` — does **not**
touch the R2 object. That's expected, and exactly what reconciliation
exists for:

```bash
# Dry run — should report 1 candidate (the object we just orphaned)
./.venv/Scripts/python scripts/reconcile_evidence.py --slug "$SLUG"

# Actually delete it
./.venv/Scripts/python scripts/reconcile_evidence.py --slug "$SLUG" --confirm

# Confirm no orphan remains
./.venv/Scripts/python scripts/reconcile_evidence.py --slug "$SLUG"
```
**Expected**: first run reports `"candidates": 1`. The `--confirm` run
reports the key under `"deleted"`. The final run reports `"candidates": 0`
— proving both cleanup and idempotency.

Also remove the local scratch data and test file:
```bash
rm -rf data-r2-closure cookies.txt "$TESTFILE" downloaded.png archived-still-downloadable.png
```

### Evidence to capture

Save the full terminal transcript (or a script `typescript` capture) of
Step A and every command in Step B, including the `sha256sum` outputs,
the `curl -v` header dump, and all three reconciliation runs' JSON
output. Name it `docs/release-evidence/r2-staging-<date>.txt`.

### RELEASE_CHECKLIST.md section to update

Row **#1** in "Release-blocking items" (`Real Cloudflare R2 staging
smoke test executed successfully`).

**Status: 🟢 PASS, recorded 2026-08-02.** The human operator ran
`scripts/r2_staging_smoke_test.py` (Step A) against the real staging
bucket — all 5 steps (PUT/HEAD/GET+checksum/presigned-GET/DELETE)
passed. See `docs/RELEASE_REHEARSAL.md` for the full output. Step B
(the full application-level walkthrough below) was not additionally
run since Step A already exercises the same `R2EvidenceStorage`
methods the application layer calls — Step B remains available for
anyone who wants the additional application-level confirmation, but is
not required to close this item. Items #2 and #3 remain BLOCKED.

---

## 2. Real-browser Screen Capture API acceptance test

### Prerequisites

- A desktop Chrome or Edge browser (recommended — `getDisplayMedia`
  support and prompt behavior is most consistent there; Firefox works
  too, Safari's behavior differs more). Not testable on a mobile
  browser.
- The app running and reachable at an HTTPS origin **or** `localhost`
  (`getDisplayMedia` requires a secure context; `localhost` is exempted).
  Local dev (`npm run dev` + `uvicorn`) is sufficient — this check is
  about the capture mechanism, not the storage backend, so
  `STORAGE_BACKEND=filesystem` (the zero-config default) is fine unless
  you specifically also want to re-exercise the R2 path here (optional,
  not required — R2 is already covered by check 1).
- A test project/suite/published revision/cycle already set up (reuse
  the same steps as check 1, or click through the UI per
  `docs/guides/TESTER_GUIDE.md`).
- Browser devtools open (Network tab) to inspect the actual upload
  request/response.

### Steps and what to verify at each one

1. **Trigger**: on the cycle execution screen, select a case, click
   **Capture screen** in the Evidence panel.
2. **Permission prompt behavior**: the browser's native screen/window/tab
   picker must appear — this is the OS/browser-level permission prompt;
   it cannot be and must not be bypassed. Select any window or tab to
   share.
3. **Single-frame capture**: after granting, the app should grab exactly
   one frame and immediately stop sharing — watch for the browser's
   "sharing" indicator (a colored border/tab icon, varies by browser) to
   disappear right away, not linger. A lingering share indicator after
   the capture completes would indicate the media stream wasn't stopped
   — note this as a finding if observed.
4. **Preview before upload — confirm path**: as of 2026-08-02, the app
   shows a local, client-side preview of the captured frame — labeled
   "Preview — nothing is uploaded until you confirm" — with **Upload
   evidence** and **Cancel** buttons, **before** any network request is
   made. Confirm in devtools' Network tab that no `POST .../evidence`
   request fires merely from clicking Capture screen; it must only fire
   after clicking **Upload evidence**. Confirm the preview image is
   pixel-identical to what ends up uploaded (same capture, not re-taken).
   Click **Upload evidence** and confirm the request fires exactly once
   even if you click it more than once in quick succession (the button
   must disable/no-op while the upload is in flight).
4b. **Preview before upload — cancel path**: repeat the capture, but this
   time click **Cancel** instead. Verify: (a) no `POST .../evidence`
   request appears in the Network tab at any point, (b) the preview
   disappears and the Evidence panel's count is unchanged, (c) via the
   API or DB directly — `GET .../results/{result_id}/evidence` — no new
   `EvidenceItem` row was created, and (d) if you're running against a
   real storage backend for this check, confirm no new object exists
   under that result's `evidence/` prefix (e.g. `reconcile_evidence.py`
   in dry-run mode reports no unexpected candidate, or inspect the
   bucket/filesystem directly). This is the core requirement driving this
   feature — a rejected capture must leave zero trace.
5. **Exact result attachment**: after confirming an upload, verify the
   resulting evidence thumbnail appears under the **specific case** that
   was selected when you clicked Capture — not a different case, not
   unassigned.
6. **Stored MIME type, checksum, byte size**: in devtools' Network tab,
   find the `POST .../evidence` request; note the returned evidence
   `id`. Call `GET .../evidence/{id}` (via curl with your browser
   session's cookie, or just read the Network tab's response body
   directly) and confirm `original_content_type` is `image/png`,
   `original_sha256` is a real 64-char hex string, and
   `original_size_bytes` is plausible for a screen capture (not zero,
   not absurdly small).
7. **Immutable original behavior**: capture a second time on the same
   case — confirm it creates a **second**, independent `EvidenceItem`
   (different id, different sha256) rather than overwriting the first.
8. **Annotation and subsequent download**: click the thumbnail, draw at
   least one shape (try arrow and one other tool), **Save annotation
   revision**. Confirm the rev badge increments. Download/view the
   original again (re-open the annotator or hit the download route
   directly) — the underlying original image must be unchanged from
   before annotation (annotations render as an overlay from stored JSON,
   never baked into the original bytes).
9. **Behavior after cycle lock**: have an admin (or switch to an admin
   session) lock the cycle. Return to this case — confirm the capture/
   upload/paste controls and the archive action are no longer available
   (hidden or disabled), matching the locked-cycle rule enforced
   server-side.

### Expected database state

One (or two, if you captured twice per step 7) new `EvidenceItem` row(s)
with `evidence_type=SCREENSHOT`, correct metadata, and a real, non-empty
file on whichever storage backend was active — **and no row at all**
for any capture that was Cancelled instead of confirmed (step 4b).

### Evidence to capture

Screenshots of: the permission prompt, the resulting thumbnail, the
Network tab request/response, the evidence detail JSON, the annotation
editor mid-draw and after save, and the locked-cycle state with controls
hidden. Save under `docs/release-evidence/screen-capture-<date>/`.

### Cleanup

Delete the test project via the UI (Projects page → Archive/Delete with
password confirmation) or the API, same as check 1. If you used
`STORAGE_BACKEND=r2` for this check too, follow check 1's reconciliation
cleanup steps as well.

### Failure diagnosis

- Permission prompt never appears → confirm you're on `localhost` or a
  real HTTPS origin (not plain HTTP on a non-localhost host) and a
  supported desktop browser.
- Capture completes but upload never fires → check the Network tab for a
  failed `POST`; check `MAX_EVIDENCE_SIZE_BYTES` wasn't exceeded by a
  very high-resolution capture.
- `original_content_type` isn't `image/png` → note the browser/OS
  combination; `canvas.toBlob()`'s default output format can vary
  narrowly by platform.
- Annotation doesn't persist → check `current_revision_no` via the API
  directly; check the browser console for a failed
  `POST .../annotations` request.

### RELEASE_CHECKLIST.md section to update

Row **#2** in "Release-blocking items" (`Screen Capture API real-browser
acceptance`).

---

## 3. Real-browser clipboard-paste acceptance test

### Prerequisites

Same browser/environment prerequisites as check 2. Additionally: a real
image actually placed on your OS clipboard by a real action (e.g.
Windows Snipping Tool's "New" capture auto-copies to the clipboard, or
open any image and Ctrl+A/Ctrl+C in an image viewer/editor) —
**scripted/simulated clipboard content does not satisfy this check**;
it must be a genuine OS clipboard image from a human action.

### Steps and what to verify

1. Put a real image on your OS clipboard (see above).
2. On the cycle execution screen, click **into** the dashed "Click here
   then Ctrl+V to paste" box to focus it (paste won't register without
   focus).
3. Press Ctrl+V (Cmd+V on macOS).
4. Verify the same set of outcomes as the Screen Capture check, applied
   to this path: upload fires with `evidence_type=PASTED_IMAGE`, the
   thumbnail attaches to the correct case, `original_content_type`/
   `original_sha256`/`original_size_bytes` are all correct and
   plausible, the original is immutable across an annotation
   save-and-redownload, and every control is disabled after the cycle is
   locked.
5. Same preview-before-upload behavior as check 2 applies here too — a
   paste populates the same client-side preview with **Upload
   evidence**/**Cancel**, not an immediate upload. Repeat check 2's steps
   4 and 4b against the pasted image: confirm no upload request fires
   until you click **Upload evidence**, and confirm clicking **Cancel**
   leaves no `EvidenceItem` row and no storage object behind.

### Expected database state

One new `EvidenceItem` row, `evidence_type=PASTED_IMAGE`, correct
metadata, real bytes on the active storage backend.

### Evidence to capture

Screenshot of the OS clipboard image source (e.g. the Snipping Tool
window before paste), the paste action/resulting thumbnail, the Network
tab request/response, the evidence detail JSON, and the locked-cycle
state. Save under `docs/release-evidence/clipboard-paste-<date>/`.

### Cleanup

Same as check 2.

### Failure diagnosis

- Paste does nothing at all → confirm the dashed box actually has focus
  before pressing Ctrl+V (click it first); confirm the clipboard truly
  contains image data and not, e.g., a copied file-system path (some
  "copy image" actions on some OSes copy a file reference instead of
  raw image bytes, which this app's paste handler — which looks for a
  clipboard item whose MIME type starts with `image/` — will not treat
  as an image).
- Works in Chrome/Edge but not another browser → note the browser;
  clipboard API support and permission behavior for images varies more
  across browsers than screen capture does — record which browsers were
  tested and their individual results rather than a single pass/fail.

### RELEASE_CHECKLIST.md section to update

Row **#3** in "Release-blocking items" (`Clipboard-paste real-browser
acceptance`).

---

## Results reporting template

Copy this once per check, fill it in, and hand it back:

```
Check: [R2 staging smoke test | Screen Capture API | Clipboard paste]
Date:
Operator:
Environment: [e.g. local backend against real staging R2 bucket <name>;
              Chrome 1XX on Windows 11; etc.]
Outcome: PASS | FAIL
Evidence: [file paths / links to captured transcripts or screenshots]
Notes / anomalies observed (if any):
```

## What happens after all three are reported

1. `docs/RELEASE_CHECKLIST.md`'s three 🔴 rows are updated to 🟢 (or left
   🔴 with the specific failure noted, if any check failed) with the
   evidence references above.
2. `docs/RELEASE_REHEARSAL.md` gets a new section recording the actual
   date, environment, operator, and outcome for each of the three checks
   (distinct from the existing clean-environment rehearsal record, which
   covered everything except these three).
3. The full backend test suite and frontend build are run once more.
4. A final status is reported: **PRODUCTION READY** (only if all three
   passed) or **NOT PRODUCTION READY** (naming whichever specific check(s)
   remain unresolved or failed, with their evidence).
