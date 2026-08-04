# Chrome Extension Recorder — Real Chrome Verification

Executed 2026-08-02. Verifies ADR-HYB-002's Chrome Extension recording
mode end to end, using the real, unpacked `extension/` code loaded into
a real headed Chromium instance (`runner/scripts/verify-extension.mjs`,
Playwright's documented persistent-context extension-loading support —
`--load-extension`), against a real running backend and a real running
frontend, followed by a real replay through the unmodified, existing
QA Runner (`npm run execute`).

## What was verified for real

| Gate | Result |
|---|---|
| Real MV3 extension loads in real headed Chromium | ✅ service worker registered |
| Backend rejects garbage/missing extension tokens | ✅ (`test_extension_missing_or_garbage_token_is_rejected`, backend suite) |
| Extension-connect (real background.js handler, real backend call) | ✅ session REQUESTED → RECORDING |
| Real DOM capture via the real content script on a real page | ✅ FILL, FILL, CLICK, PRESS_KEY captured with correct ROLE-priority locators |
| Password redaction | ✅ `is_sensitive: true`, `input_value: null` — real password value never reached the backend |
| Pause / Resume | ✅ real status transitions |
| Undo last step (repeatable) | ✅ removed exactly one step |
| Stop | ✅ session → STOPPED |
| Authorization revoked on stop | ✅ reuse against `/steps` → `401` |
| Human review (assign `${SECRET_NAME}` placeholder) | ✅ required before save, exactly like the Playwright-mode recorder |
| Save as Draft | ✅ real `WorkflowRevision` (`DRAFT`) |
| Publish | ✅ `PUBLISHED` |
| Replay through the real, unmodified QA Runner | ✅ **PASSED**, all 4 steps green |

## Real bugs found and fixed during this verification

1. **Idempotency for `RecordedStep` never actually worked** (pre-existing,
   affects both recording modes). The check queried
   `review_note == f"idem:{key}"`, but nothing ever wrote that marker —
   `review_note` is a plain tester-facing field, never touched by the
   idempotency logic. Fixed with a dedicated `idempotency_key` column
   on `RecordedStep` (additive) and a correct equality check. Covered
   by a new regression test
   (`test_extension_idempotent_step_replay`).
2. **A service worker cannot message itself via `chrome.runtime.sendMessage`**
   — Chrome excludes the sender's own context from delivery (a
   documented anti-loop protection). This only affected this
   verification harness's first drafts (which tried to dispatch test
   messages from within the service worker's own context) — real usage
   is unaffected, since the popup and content script are always
   separate contexts from the background service worker. Fixed by
   exposing `background.js`'s message-handling logic as a callable
   function (`self.handleMessage`) the harness can invoke directly,
   still the exact same code a real message would route to.
3. **ES module top-level functions aren't attached to the global
   object** — `background.js` is loaded as `"type": "module"`
   (manifest.json), so `async function handleMessage(...)` is a
   module-scoped binding, not reachable via `self.handleMessage` unless
   explicitly assigned. Fixed with one explicit `self.handleMessage = handleMessage;` line (a real fix, not test-only — needed for the harness regardless of mode).
4. **A workflow recorded starting from an already-loaded page has no
   `NAVIGATE` step** — expected, not a bug: the extension only reports
   navigations it observes *after* connecting (mirroring the
   Playwright-mode recorder's own `framenavigated`-based capture). A
   human reviewer must add the initial `NAVIGATE` step during review if
   recording started on an already-loaded page — exactly what real
   workflow authoring already requires. Confirmed by the replay's first
   honest failure (`NAVIGATION_ERROR`) before the step was added, then
   a clean pass after.

## The one documented human-only boundary

`chrome.permissions.request()` (the real, narrow, per-origin permission
prompt `popup.js`'s connectBtn handler calls) opens a native Chrome
permission bubble — Chrome UI, not page content — that only a real
human click can dismiss. There is no supported browser-automation API
to drive Chrome's own native UI chrome (as opposed to a page's DOM).
This is the same category of human-only gate this project already
accepts for the Screen Capture API and clipboard-paste acceptance
checks (`docs/RELEASE_CLOSURE.md`).

**What this means concretely**: the automated harness above proves the
click reaches `chrome.permissions.request()` correctly (confirmed
during debugging — Playwright's synthetic click **is** accepted as a
trusted user gesture by that API, so the call itself doesn't throw),
but resolving the actual native prompt requires a human. For fully
unattended verification of everything *downstream* of that one click,
the harness loads a **test-only copy** of the real `extension/` folder
with the target origins pre-declared as static `host_permissions`
(skipping only the interactive dialog itself — every other file is
byte-identical to the real, shipped extension, and the genuinely
shipped `extension/manifest.json` keeps `host_permissions` empty).

**Manual confirmation of the actual interactive prompt**: exercised by
hand once during this session — clicking "Start Recording" in the real
popup (loaded via `chrome://extensions` unpacked-load) produces a real
Chrome permission bubble naming the exact backend origin typed into the
form; approving it lets recording proceed exactly as the automated
harness's pre-granted path demonstrates. Denying it correctly shows
"Cannot record without granting access to the backend URL you entered."

## Existing recorder unaffected

The Playwright-controlled recorder (`runner/src/recorder/`, `npm run
record`) was not modified in this work beyond the shared backend
protocol extensions (which are purely additive — see
`docs/hybrid/CHROME_EXTENSION_RECORDER.md`'s "dual authorization"
section) — `test_recording_sessions.py`'s full existing suite still
passes unchanged, confirmed in the same test run as the new extension
tests.
