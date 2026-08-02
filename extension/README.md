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
   mints a short-lived, session-scoped **pairing code** and shows it
   once. Copy it.
3. Navigate to the target application tab you want to record.
4. Click the QA-Again Recorder extension icon, paste the pairing code
   into the one text box, and click **Start Recording on This Tab**.
   (Advanced: the four individual fields — backend URL, project slug,
   session ID, token — are still available under "Advanced: enter
   fields manually instead" if you ever need to type them by hand.)
5. A real Chrome permission prompt appears asking to grant access to
   the backend origin the pairing code names (never a broader grant).
   Approve it.
6. Interact with the target application normally in that same tab.
   Captured steps appear live in QA-Again's Recording panel.
7. Use **Pause**/**Resume**/**Undo last action**/**Stop** from either
   the extension popup or QA-Again's own UI — both call the same
   backend endpoints.
8. Once stopped, review the captured steps in QA-Again (edit/delete/
   reorder, same as the Playwright mode), assign `${SECRET_NAME}`
   placeholders for any sensitive fields, then **Save as Draft** and
   publish — identical to the existing recorder's review/publish flow.

## Troubleshooting

- **Extension icon does nothing / not pinned**: confirm it's actually
  loaded at `chrome://extensions` (Developer mode → Load unpacked →
  this `extension/` folder), then pin it via the toolbar's puzzle-piece
  menu.
- **"Pairing code is not valid"**: it was cut off when copying, or
  copied from a previous session. Go back to QA-Again and click
  **Authorize Extension** again for the current session — each code is
  minted fresh and single-use per session.
- **Nothing captured after Start Recording**: the tab that was
  *active* when you clicked the extension icon is the one that gets
  recorded (`activeTab` permission). Make sure the target app's tab is
  the foreground tab before clicking the icon.
- **Permission prompt denied**: click the extension icon again and
  retry — recording cannot start without granting access to the one
  backend origin named in the prompt.
- **Session stuck at REQUESTED**: it never successfully connected.
  **Discard** it in QA-Again and create a new `RecordingSession` — a
  session can only be authorized once.
- **"Could not connect" / network error**: the pairing code's backend
  URL was minted before the backend restarted or a port changed. Get a
  fresh pairing code from a new (or the same, if still `REQUESTED`)
  session.

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
