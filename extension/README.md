# QA-Again Recorder (Chrome Extension)

Everyday recording mode — see `docs/adr/ADR-HYB-002-chrome-extension-recorder.md`
and `docs/hybrid/CHROME_EXTENSION_RECORDER.md` for the full design. The
existing Playwright-controlled recorder (`runner/`, `npm run record`)
remains available as the advanced/fallback mode — unchanged.

## Install (unpacked, for development/internal use — not published to
the Chrome Web Store)

1. Open `chrome://extensions`.
2. Enable **Developer mode** (top right).
3. **Load unpacked** → select this `extension/` folder.
4. Pin the "QA-Again Recorder" icon to the toolbar for convenience.

## Usage

1. In QA-Again's own UI, create a Workflow and a `RecordingSession`
   (target URL, workflow) exactly as today.
2. Click **Authorize Extension** in QA-Again's Recording panel — this
   mints a short-lived, session-scoped token and shows it once. Copy
   it.
3. Navigate to the target application tab you want to record.
4. Click the QA-Again Recorder extension icon.
5. Fill in: Backend URL, Project slug, Session ID (from step 1), and
   the pasted Extension authorization token (from step 2).
6. Click **Start Recording** — a real Chrome permission prompt appears
   asking to grant access to the exact backend URL you entered (never
   a broader grant). Approve it.
7. Interact with the target application normally in that same tab.
   Captured steps appear live in QA-Again's Recording panel.
8. Use **Pause**/**Resume**/**Undo last action**/**Stop** from either
   the extension popup or QA-Again's own UI — both call the same
   backend endpoints.
9. Once stopped, review the captured steps in QA-Again (edit/delete/
   reorder, same as the Playwright mode), assign `${SECRET_NAME}`
   placeholders for any sensitive fields, then **Save as Draft** and
   publish — identical to the existing recorder's review/publish flow.

## What this extension does NOT do

- No `host_permissions` are granted at install time — only `activeTab`
  (the currently active tab, only after you click the extension icon)
  and an explicit, narrow, per-use grant for the one backend origin you
  type in.
- No global OS keyboard/mouse capture — only ordinary DOM event
  listeners on the one authorized tab, only while a session is
  `RECORDING`.
- No cookies, `localStorage`/`sessionStorage`, or HTTP header access —
  the extension has no permission that would grant any of that
  visibility, and the content script has none of that DOM API surface
  available to it regardless.
- No real password/OTP/token/card value ever leaves the content
  script — sensitive fields are redacted before the very first message
  is sent to the background service worker.
- No global RunnerToken and no user JWT are ever stored in the
  extension — only the short-lived, single-session authorization,
  stored in `chrome.storage.session` (cleared when the browser closes).

## Files

- `manifest.json` — Manifest V3, no `host_permissions`.
- `popup.html` / `popup.js` — the toolbar popup UI; where the optional
  host-permission request happens (user-gesture context).
- `background.js` — service worker; holds the session config, forwards
  captured events to the backend, injects the content script, reports
  real navigations.
- `content.js` — injected into the one authorized tab on Start; the
  actual DOM-event listener + locator-computation + redaction logic
  (ported from `runner/src/recorder/domRecorder.ts` for parity with the
  Playwright-mode recorder — same locator vocabulary, same
  noise-reduction, same sensitive-field handling).
