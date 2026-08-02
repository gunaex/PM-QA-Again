// Shared browser-lifecycle helper for the HYB-5 headed-Chrome
// verification scripts (verify-quick-manual-test.mjs, verify-extension.mjs).
// Mirrors runner/src/browser/browserRun.ts (kept as a separate plain-JS
// copy because these scripts run directly via `node`, not through tsc)
// -- see that file's comments for the full rationale. Every browser this
// launches gets its own uniquely-named, tracked profile directory
// (prefix "qa-again-playwright-") and is closed via ordered, idempotent
// cleanup on success, thrown error, timeout, Ctrl+C, SIGTERM,
// uncaughtException, and unhandledRejection.

import { chromium } from "playwright";
import { mkdirSync, readdirSync, readFileSync, rmSync, unlinkSync, writeFileSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { randomBytes } from "node:crypto";

export const PROFILE_PREFIX = "qa-again-playwright-";

const REGISTRY_DIR = join(tmpdir(), "qa-again-playwright-registry");
const STALE_ENTRY_MS = 30 * 60 * 1000;
const DEFAULT_MAX_CONCURRENT = 3;

function ensureRegistryDir() {
  mkdirSync(REGISTRY_DIR, { recursive: true });
}

function registryFilePath(runId) {
  return join(REGISTRY_DIR, `${runId}.json`);
}

function listLiveRegistryEntries() {
  ensureRegistryDir();
  const now = Date.now();
  const out = [];
  for (const file of readdirSync(REGISTRY_DIR)) {
    if (!file.endsWith(".json")) continue;
    try {
      const entry = JSON.parse(readFileSync(join(REGISTRY_DIR, file), "utf-8"));
      if (now - new Date(entry.launchedAt).getTime() < STALE_ENTRY_MS) out.push(entry);
    } catch {
      // ignore unreadable/partial registry files
    }
  }
  return out;
}

async function waitForConcurrencySlot(maxConcurrent) {
  // eslint-disable-next-line no-constant-condition
  while (true) {
    if (listLiveRegistryEntries().length < maxConcurrent) return;
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
}

const activeRuns = new Set();
let signalHandlersRegistered = false;

function registerSignalHandlersOnce() {
  if (signalHandlersRegistered) return;
  signalHandlersRegistered = true;

  const closeAllTrackedRuns = async () => {
    const runs = [...activeRuns];
    await Promise.all(
      runs.map((run) =>
        run.close().catch((err) => {
          console.error(`[browserLifecycle] cleanup failed for run ${run.runId}:`, err);
        }),
      ),
    );
  };

  const handleSignal = (signal, exitCode) => {
    process.once(signal, () => {
      console.error(`[browserLifecycle] ${signal} received -- closing ${activeRuns.size} tracked browser run(s) before exit`);
      closeAllTrackedRuns().finally(() => process.exit(exitCode));
    });
  };
  handleSignal("SIGINT", 130);
  handleSignal("SIGTERM", 143);

  process.on("uncaughtException", (err) => {
    console.error("[browserLifecycle] uncaughtException -- closing tracked browser run(s) before exit:", err);
    closeAllTrackedRuns().finally(() => process.exit(1));
  });
  process.on("unhandledRejection", (reason) => {
    console.error("[browserLifecycle] unhandledRejection -- closing tracked browser run(s) before exit:", reason);
    closeAllTrackedRuns().finally(() => process.exit(1));
  });
}

/**
 * Launches one QA-Again-owned, uniquely-profiled, tracked headed Chromium
 * instance via launchPersistentContext. Returns { runId, userDataDir,
 * context, page, close() }. `close()` is idempotent and safe to call from
 * both the caller's own try/finally and a signal handler.
 *
 * opts: { label, headless, slowMo, args, maxConcurrent }
 */
export async function launchTrackedBrowser(opts) {
  registerSignalHandlersOnce();

  const maxConcurrent = opts.maxConcurrent ?? Number(process.env.QA_AGAIN_MAX_CONCURRENT_BROWSERS ?? DEFAULT_MAX_CONCURRENT);
  await waitForConcurrencySlot(maxConcurrent);

  const safeLabel = String(opts.label ?? "run").replace(/[^a-zA-Z0-9._-]/g, "-");
  const runId = `${safeLabel}-${Date.now()}-${randomBytes(4).toString("hex")}`;
  const userDataDir = join(tmpdir(), `${PROFILE_PREFIX}${runId}`);
  mkdirSync(userDataDir, { recursive: true });

  const context = await chromium.launchPersistentContext(userDataDir, {
    headless: opts.headless ?? false,
    slowMo: opts.slowMo,
    args: opts.args ?? [],
  });

  ensureRegistryDir();
  writeFileSync(
    registryFilePath(runId),
    JSON.stringify({ runId, userDataDir, label: opts.label ?? null, launchedAt: new Date().toISOString(), pid: null }, null, 2),
  );

  const page = context.pages()[0] ?? (await context.newPage());

  let closed = false;
  const handle = {
    runId,
    userDataDir,
    context,
    page,
    async close() {
      if (closed) return;
      closed = true;
      activeRuns.delete(handle);

      try {
        if (!page.isClosed()) await page.close();
      } catch (err) {
        console.error(`[browserLifecycle] run ${runId}: page.close() failed (continuing cleanup):`, err);
      }
      try {
        await context.close();
      } catch (err) {
        console.error(`[browserLifecycle] run ${runId}: context.close() failed (continuing cleanup):`, err);
      }
      try {
        unlinkSync(registryFilePath(runId));
      } catch {
        // already removed, or never fully written -- fine either way.
      }
      try {
        rmSync(userDataDir, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
      } catch (err) {
        console.error(`[browserLifecycle] run ${runId}: failed to remove profile dir ${userDataDir} (may need operator cleanup):`, err);
      }
    },
  };
  activeRuns.add(handle);
  return handle;
}

export function isRunFullyCleanedUp(runId, userDataDir) {
  return !existsSync(registryFilePath(runId)) && !existsSync(userDataDir);
}

export function listOwnedRegistryEntries() {
  return listLiveRegistryEntries();
}

export { REGISTRY_DIR };
