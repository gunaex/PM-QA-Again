# Headed-browser process cleanup

## The defect this fixes

Verification runs (and, less often, real runner/recorder sessions) were
leaving headed Chrome/Chromium processes and "Test" profile windows open
after completion. Root causes, found by auditing every Playwright
launch site in the repo:

1. `runner/scripts/verify-quick-manual-test.mjs` and
   `runner/scripts/verify-extension.mjs` called `chromium.launch()` /
   `chromium.launchPersistentContext()` with a bare `browser.close()` /
   `context.close()` statement reached only if every step before it
   succeeded. Any thrown assertion, timeout, or selector failure (both
   scripts have over a dozen such throw sites) skipped the close call
   entirely.
2. No launch site anywhere in the repo (`executor.ts`, `recordSession.ts`,
   `spike.ts`, or the two verification scripts) registered
   `SIGINT`/`SIGTERM`/`uncaughtException`/`unhandledRejection` handlers,
   so killing the Node process externally (Ctrl+C, a stopped debug
   session, a cancelled CI job) always orphaned the browser regardless of
   how clean the in-process `try/finally` was.
3. No launch site tracked a PID or a named user-data-dir, so a leftover
   process/profile could never be attributed back to QA-Again, and no
   operator cleanup script existed at all.
4. `verify-extension.mjs` also leaked its `fs.mkdtempSync` test-extension
   copy directory on every path (no cleanup, success or failure).

## The fix

Every headed browser QA-Again launches now goes through one of two
equivalent shared helpers:

- `runner/src/browser/browserRun.ts` (`launchTrackedBrowser`) -- used by
  `executor.ts` (HYB-2 execution + HYB-4 checkpoint pause/resume),
  `recordSession.ts` (HYB-3 recorder), and `spike.ts` (HYB-0).
- `runner/scripts/lib/browserLifecycle.mjs` -- the same design, in plain
  JS, used by `verify-quick-manual-test.mjs` and `verify-extension.mjs`
  (these run directly via `node`, not through `tsc`).

Both helpers:

- Launch via `chromium.launchPersistentContext(userDataDir, ...)` with an
  explicit, uniquely-named profile directory
  (`qa-again-playwright-<label>-<timestamp>-<random>` under the OS temp
  dir) -- never Playwright's own anonymous temp profile. This is what
  makes an orphaned process/profile identifiable and safely killable
  after the fact.
- Never call a separate `browser.close()` -- `launchPersistentContext`
  does not return a `Browser`; only `context.close()` exists and is used.
- Close in order (`page.close()` -> `context.close()`), remove the
  profile directory, and remove a small JSON registry entry, all inside
  one idempotent `close()` -- safe to call more than once (a normal
  `finally` and a signal handler can both race to call it).
- Write that JSON registry entry (run id, profile dir, label, launch
  time) to `<tmp>/qa-again-playwright-registry/` immediately after
  launch, and remove it on `close()`. This is what the concurrency
  limiter and the operator cleanup scripts read.
- Register `process.on('SIGINT' | 'SIGTERM' | 'uncaughtException' |
  'unhandledRejection', ...)` exactly once per process, closing every
  still-tracked browser run before the process exits on any of those
  paths.
- Cap concurrently-active QA-Again browsers (default 3, override via
  `QA_AGAIN_MAX_CONCURRENT_BROWSERS`) so a retry storm or several manual
  invocations at once cannot open dozens of headed browsers
  simultaneously; registry entries older than 30 minutes are treated as
  abandoned and stop counting against the limit (a crashed process
  should not permanently jam future launches).

Callers keep using an ordinary `try { ... } finally { await run.close(); }`
around their own logic -- the helper's signal handlers are the backstop
for the case that pattern can't cover (the process dying instead of the
promise rejecting).

`verify-extension.mjs`'s temporary extension-copy directory
(`fs.mkdtempSync`, unrelated to the browser profile dir) is now removed
in the same `finally` block.

## Operator cleanup scripts

If a process is killed hard enough that even the signal handlers can't
run (e.g. `kill -9` / Task Manager "End task", a host crash, a debugger
force-stop), a browser can still be orphaned. Both scripts below find and
optionally terminate **only** processes whose command line references a
`qa-again-playwright-*` profile directory -- they never touch a
tester's normal Chrome/Edge session, and never do a blanket
`taskkill /IM chrome.exe` / `pkill chrome`.

**Windows:**

```powershell
# List only (safe default)
.\runner\scripts\cleanup-qa-again-browsers.ps1

# Terminate and remove profile dirs for processes older than 10 minutes
.\runner\scripts\cleanup-qa-again-browsers.ps1 -Kill -OlderThanMinutes 10
```

**macOS/Linux:**

```bash
# List only (safe default)
./runner/scripts/cleanup-qa-again-browsers.sh

# Terminate and remove profile dirs for processes older than 10 minutes
./runner/scripts/cleanup-qa-again-browsers.sh --kill --older-than 10
```

## Acceptance check

`runner/scripts/verify-browser-cleanup.mjs` runs three real headed-Chrome
scenarios through `launchTrackedBrowser` -- a normal success, a
deliberate thrown failure, and an abandoned/timed-out action -- and
asserts zero QA-Again-owned registry entries (and therefore zero
processes/profile dirs) remain after each one:

```bash
cd runner
node scripts/verify-browser-cleanup.mjs
```
