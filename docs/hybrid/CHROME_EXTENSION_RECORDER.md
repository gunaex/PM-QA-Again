# Chrome Extension Recorder — Design

See `docs/adr/ADR-HYB-002-chrome-extension-recorder.md` for why this
mode was chosen. This document is the concrete design: authorization
model, message flow, locator priority, redaction rules, and the new
"undo last step" control.

## What stays exactly the same

`RecordingSession`, `RecordedStep`, the review/edit endpoints
(`PUT/DELETE .../steps/{id}`, reorder, insert-checkpoint, locator-test),
and `save-as-draft` → `WorkflowRevision`/`WorkflowStep` → publish are
**completely unchanged and fully reused**. The extension is a second
way to populate the same `RecordedStep` buffer the Playwright recorder
already writes to — never a parallel model.

## New credential: `RecordingSessionAuthorization`

Neither the tester's normal JWT (long-lived, broad — every project the
user can reach) nor the global `RunnerToken` (long-lived, every
project) is appropriate to embed in a browser extension. A new,
narrower credential:

```python
class RecordingSessionAuthorization(ProjectBase):
    id: int
    recording_session_id: int  # FK -- scoped to exactly ONE session
    token_hash: str            # SHA-256, same discipline as RunnerToken/RefreshToken
    issued_by: str             # tester email, server-derived
    issued_at: datetime
    expires_at: datetime       # short-lived -- 30 minutes, renewable by heartbeat up to a hard cap
    revoked: bool
    revoked_at: datetime | None
```

- Minted only by a real, authenticated `require_tester` user session,
  scoped to a `recording_session_id` that user just created.
- The raw token is returned **once**, exactly like `RunnerToken`/
  `RefreshToken` minting.
- Expires in 30 minutes; the extension's background worker renews it
  (heartbeat) while actively recording, up to a **hard cap of 4 hours
  total per session** — a genuinely short-lived credential, not an
  indefinitely-renewable one.
- Revoked immediately on `stop`/`discard`, and by the same lazy
  lease-expiry-sweep pattern already used for `RunnerToken`/lease-based
  auth elsewhere in this app.
- Scoped to exactly one `recording_session_id` — an extension holding
  this token can never touch any other session, workflow, or project.

## Message flow

```
Tester's Chrome                    QA-Again backend
───────────────                    ────────────────
1. Open target app tab (normal browsing, no extension involved yet)
2. Open QA-Again in ANOTHER tab, create/select a RecordingSession
   (existing POST /recording-sessions -- unchanged)
3. In QA-Again's own tab, click "Authorize Extension" ──►
                                      POST /{session}/authorize-extension
                                      (tester's own QA-Again login
                                      session, via the QA-Again tab's
                                      own cookies -- the extension popup
                                      itself never holds this call).
                                      Response includes pairing_code: a
                                      single base64 string bundling
                                      {backendUrl, projectSlug,
                                      sessionId, token} -- everything the
                                      popup previously needed as four
                                      hand-typed fields, packaged into
                                      one paste. Same secret, same
                                      lifetime, shown once.
4. Switch to the target tab, click the
   QA-Again Recorder extension icon
   (activeTab grant for THIS click
   only, on whichever tab is currently
   active), paste the pairing code
   into the one text box, click
   "Start Recording on This Tab" (the
   four individual fields remain
   available under an "Advanced"
   fallback for manual entry if the
   code can't be pasted)
5. Popup decodes the pairing code
   client-side and stores the
   extracted token (chrome.storage.session
   -- cleared when the browser closes,
   never chrome.storage.local)
   ──────────────────────────────►  POST /{session}/extension-connect
                                      (session REQUESTED -> RECORDING)
6. Background injects the content
   script into the active tab only
   (chrome.scripting.executeScript,
   activeTab-gated)
7. Content script observes real DOM
   events on THIS tab only, builds a
   structured locator + redacts
   sensitive values, posts to the
   background worker
8. Background batches/forwards       ────────────►  POST /{session}/steps
   (idempotency_key per event,
   same field the Playwright mode
   already uses)
9. QA-Again's own RecordingPanel
    (open in the other tab) polls
    GET /{session} and shows the
    new steps live -- same existing
    polling UI, no changes needed
10. Pause/Resume/Stop/Undo from
    EITHER the extension popup OR
    QA-Again's own UI               ────────────►  same endpoints,
                                                    dual-authorized (see
                                                    below)
11. Stop  ─────────────────────────► POST /{session}/stop
    (revokes the authorization
    immediately)
12. Human reviews/edits captured
    steps in QA-Again (unchanged),
    Save as Draft (unchanged) →
    DRAFT WorkflowRevision, human
    review + publish still required
```

## Dual authorization on shared endpoints

The following existing endpoints now accept **either** a `RunnerToken`
+ lease (unchanged, Playwright mode) **or** a valid
`RecordingSessionAuthorization` scoped to that exact
`recording_session_id` (new, extension mode) — resolved by a single
`_authorize_recorder_actor()` helper, never two separate endpoint sets:

- `POST /{session_id}/steps` (append a recorded step)
- `POST /{session_id}/heartbeat`
- `GET /{session_id}/pending-locator-tests`
- `POST /{session_id}/steps/{step_id}/locator-test-result`

And these — previously `require_tester`-only (human session) — now
also accept the extension's short-lived token, so the popup can call
them directly without ever holding the tester's own JWT:

- `POST /{session_id}/pause`
- `POST /{session_id}/resume`
- `POST /{session_id}/stop`
- `POST /{session_id}/undo-last-step` (new — see below)

`authorize-extension` itself and `extension-connect` are new, single-
purpose endpoints (minting and first-use respectively) — not a
duplicate of the claim/heartbeat pattern, just its extension-mode
equivalent using the narrower credential.

## New: "Undo last step"

A tester may make a mistake while recording (click the wrong element,
type in the wrong field). Rather than requiring a full stop + manual
delete-from-the-review-screen (which today only works once the session
is `STOPPED`), a new action lets them **walk backward one captured
step at a time, live, while still `RECORDING` or `PAUSED`**:

```
POST /{session_id}/undo-last-step
```

- Deletes exactly the single most-recently-captured `RecordedStep`
  (highest `sequence_no`) for that session.
- Callable repeatedly — each call removes one more step, walking all
  the way back to an empty buffer (the start) if needed.
- Available from both the extension popup ("Undo last action" button,
  enabled whenever at least one step has been captured) and QA-Again's
  own RecordingPanel (same button, same endpoint).
- Requires the session to be `RECORDING` or `PAUSED` (matches
  `insert-checkpoint`'s own status gate) — once `STOPPED`, the existing
  per-step `DELETE .../steps/{id}` review-screen control is used
  instead (it can delete *any* step, not just the last one, since by
  then the tester is doing a full considered review, not an in-the-
  moment correction).
- No new model — this is exactly the existing `DELETE .../steps/{id}`
  logic, just auto-targeting the last row and gated on the live-
  recording statuses instead of `STOPPED`.

## Semantic locator priority (content script)

Matches this app's existing `LOCATOR_STRATEGIES` exactly — the
extension does not invent a new locator vocabulary:

1. `data-testid` (or `data-test-id`/`data-test`) attribute → `TEST_ID`
2. Accessible role + accessible name (computed the same way
   `getByRole` would resolve it) → `ROLE`
3. `<label>` association (explicit `for`/`id` or implicit wrapping) →
   `LABEL`
4. Other stable semantic attributes (`name`, `placeholder`, `aria-label`)
   → `PLACEHOLDER` or a `CSS` attribute-selector fallback
5. Stable visible text → `TEXT`
6. CSS selector (structural, last resort) → `CSS`

Raw X/Y coordinates are captured **only** as `diagnostic_x`/
`diagnostic_y` metadata (exactly like the Playwright recorder already
does) — never as the primary locator, never resolved against during
replay.

Any step where the content script had to fall back past priority 3
(label) sets `needs_review: true` and a `review_note` explaining why —
identical noise-reduction discipline to the existing recorder.

## Redaction (sensitive input) rules

Before any event ever leaves the content script (i.e. before it's even
posted to the background worker, let alone the network):

- An `<input>` with `type="password"` is **never** captured with its
  real value. The step is recorded as `is_sensitive: true`,
  `input_value: null` immediately — the extension asks the tester (in
  the popup, after the step appears) to supply a `${SECRET_NAME}`
  placeholder before the step is included in a saved draft (mirrors
  `_validate_step_fields`'s existing server-side rule that a sensitive
  step's `input_value` must be a placeholder, never a literal value —
  enforced again, redundantly, server-side).
- Heuristic secondary detection: an input whose `name`/`id`/`aria-label`
  matches `/token|secret|otp|passcode|cvv|card.?number/i` is also
  treated as sensitive by default (tester can override), even if
  `type` isn't `password` — reduces the chance of an OTP or API-key
  field slipping through as a "normal" FILL step.
- The content script never reads `document.cookie`, never reads
  `localStorage`/`sessionStorage`, never reads HTTP response headers
  (it has no visibility into them at all — content scripts don't see
  network headers), and never requests any permission that would grant
  that visibility (no `cookies` permission, no `webRequest` permission
  in the manifest).
- No global OS-level keyboard/mouse hook of any kind — every captured
  event is a normal DOM event listener (`click`, `input`, `change`,
  `submit`, `keydown` filtered to a small allow-list of semantically
  meaningful keys) attached only to the one authorized tab's own
  document, only while a session is actively `RECORDING`.

## Manifest V3 permission model

```json
{
  "manifest_version": 3,
  "permissions": ["activeTab", "scripting", "storage"],
  "host_permissions": [],
  "action": { "default_popup": "popup.html" },
  "background": { "service_worker": "background.js", "type": "module" }
}
```

No `host_permissions` at all — the extension can only ever act on
whichever tab was active at the moment the user clicked the toolbar
icon (`activeTab`), and only for the duration of that user gesture's
grant. `chrome.scripting.executeScript` (not a manifest-declared
content script) is used to inject the recorder script on demand, into
that one tab, only after the user has explicitly clicked "Start
Recording" — never automatically, never on every page load, never on
tabs the user hasn't interacted with the extension on.

Cross-origin calls to the QA-Again backend (`fetch()` from the
background service worker) do **not** require `host_permissions` for
the backend's own origin under Manifest V3 as long as the extension
only reads/writes its own request/response bodies (no DOM access to
that origin) — this is a plain authenticated API call, exactly like
the Node.js runner already makes, just from a service worker instead
of a Node process.
