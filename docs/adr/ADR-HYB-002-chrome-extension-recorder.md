# ADR-HYB-002 — Chrome Extension recording mode as the primary everyday recorder UX

Status: accepted
Date: 2026-08-02
Companion documents: `docs/hybrid/HYB-1-GAP-ANALYSIS-REFRESH.md`,
`docs/hybrid/HYBRID_RUNNER_THREAT_MODEL.md`

## Context

HYB-3's recorder requires a tester to run `npm run record` in a
terminal, which then launches a **separate, runner-controlled**
Chromium window — never the tester's own everyday browser tab. This is
correct and secure (recording only ever happens inside a controlled,
disposable browser instance, matching this app's "outbound-only
runner" trust model), but it is a real UX barrier for ordinary testers
who don't run terminal commands day to day. The user has asked for a
lower-friction "record in my own browser tab" mode, while keeping the
existing mode available as an advanced/fallback option.

Four options were evaluated.

## Option 1 — Keep only the existing Playwright-controlled recorder

**Pros**: already built, already verified (HYB-3), zero new attack
surface, the browser instance is fully controlled/disposable so there
is no question of what a "normal" browsing session might leak.
**Cons**: requires a terminal + a runner token + a separate window every
time — real, demonstrated friction (this is exactly what prompted this
request). Does not scale to "ordinary users" without CLI comfort.
**Verdict**: keep as the advanced/fallback mode (unchanged), but does
not by itself solve the UX problem.

## Option 2 — Chrome Extension (Manifest V3), recording the user's own active tab

**Pros**: no terminal, no separate window — the tester works in their
normal tab, exactly matching the requested UX (open the app, click the
extension, Start Recording). MV3's `activeTab` permission model means
the extension has **no host access at all** until the user explicitly
invokes it via a toolbar-icon click (a user gesture) — this is a
narrower, more auditable grant than a permanent host permission, and
strictly narrower than what the existing Playwright mode already
implicitly trusts (a runner-controlled browser with full page access).
A content script can compute the same structured locators (`data-testid`
→ role/name → label → stable attribute → text → CSS) this app already
uses for replay, and never needs to touch OS-level input, cookies, or
`localStorage` to do it — DOM-level event listeners are sufficient.
**Cons**: new code surface (extension + a new short-lived,
session-scoped authorization mechanism on the backend, since neither
the tester's long-lived JWT nor the global `RunnerToken` should ever
live inside an extension — see Security section below). Extensions
require Chrome-specific packaging/distribution (fine — this app
already documents Chrome-specific setup for the recorder's Playwright
Chromium dependency, so a Chrome-specific tool isn't a new category of
constraint).
**Verdict**: **selected**. No concrete security or platform blocker was
found; the `activeTab` model is a genuine security improvement over a
hypothetical always-on host-permission extension, and it directly
satisfies the requested UX without touching the existing controlled-
browser mode.

## Option 3 — iframe embedding of the target app inside QA-Again

**Cons, disqualifying**: most modern web applications (including
QA-Again's own target apps in realistic use) send `X-Frame-Options`/
`frame-ancestors` CSP headers that block being iframed by a third-party
origin — this would silently fail against a large fraction of real
target applications, which defeats the entire purpose of a general-
purpose recorder. Even where framing succeeds, a recorder embedded via
iframe cannot observe cross-origin DOM/input events at all (same-origin
policy) unless the target app cooperates, which it generally won't.
Also reintroduces a permanent, broad access pattern (the parent frame
attempting rich instrumentation of arbitrary embedded content) that is
a strictly worse security posture than `activeTab`.
**Verdict**: rejected — not a matter of preference, a platform blocker
for most real target applications.

## Option 4 — Streamed remote browser (a server-side headless/headed browser, video/DOM-streamed to the tester's own browser)

**Pros**: would give the tester "my own tab" ergonomics without any
extension, and the actual recording browser stays fully controlled
(same trust model as the existing Playwright mode).
**Cons, disqualifying for "primary everyday" status**: substantially
larger build (a remote-desktop-style streaming protocol, or a DOM-sync
protocol, plus server-side browser pooling/lifecycle management) for a
capability this MVP does not need — this app explicitly has no goal of
cloud-scale parallel browser farms (see `docs/ROADMAP.md`'s Track B
non-goals). It also reintroduces exactly the terminal/runner-process
dependency Option 1 already has (a server-side browser still needs to
be launched and supervised by something), just moved to a hosted
location instead of the tester's own machine — it does not remove the
operational dependency, only relocates it. Real added latency/fidelity
loss (video or DOM-diff streaming is never pixel-perfect input fidelity)
compared to a content script observing the real DOM directly.
**Verdict**: rejected as the *primary* mode — worth revisiting only if
a future requirement specifically needs centrally-hosted, disposable
recording browsers (e.g. a SaaS multi-tenant deployment), which is
explicitly out of scope for this internal MVP (see
`docs/HYBRID_RUNNER_THREAT_MODEL.md` §4's internal-MVP-only decision).

## Decision

**Chrome Extension (Manifest V3) recording becomes the primary,
everyday recording UX.** The existing Playwright-controlled recorder
(`npm run record`) remains available, unchanged, as the advanced/
fallback mode — e.g. for testers who need to record without installing
a browser extension, or want the fully-disposable-browser guarantee.

Neither replaces `RecordingSession`/`RecordedStep` or the workflow
draft/publish model — the extension is a **second way to populate the
exact same `RecordedStep` buffer** the Playwright recorder already
writes to, reviewed and saved through the exact same
`save-as-draft`/publish pipeline. See
`docs/hybrid/CHROME_EXTENSION_RECORDER.md` for the full design
(authorization model, message flow, locator priority, redaction rules).

## Consequences

- A new, short-lived, recording-session-scoped authorization token type
  is added (`RecordingSessionAuthorization`) — distinct from both the
  tester's JWT and the global `RunnerToken`, expiring quickly and
  revoked on stop/expiry. This is a deliberate, narrower credential than
  either existing one; it is *not* a relaxation of the existing runner-
  token trust model.
- `RecordedStep`/`RecordingSession` gain no new columns beyond one
  nullable link (`extension_authorization_id`) to record which
  authorization (if any) populated a given session — additive, matching
  this app's existing schema-evolution discipline.
- The existing runner-facing endpoints (`/claim`, `/heartbeat`,
  `/steps`, locator-test endpoints) are extended to accept *either* a
  `RunnerToken`+lease (existing Playwright mode) *or* a valid
  `RecordingSessionAuthorization` scoped to that exact session
  (extension mode) — never a new parallel set of endpoints.
