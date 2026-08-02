import { chromium, type BrowserContext, type Page } from "playwright";
import { mkdirSync, readdirSync, readFileSync, rmSync, unlinkSync, writeFileSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { randomBytes } from "node:crypto";

/** Every QA-Again-owned Chromium profile directory (and therefore every
 * process launched against it) is named with this prefix so an operator
 * -- or the cleanup scripts in runner/scripts/cleanup-* -- can identify
 * and safely reap ONLY processes this tool launched, never a tester's
 * normal Chrome. See docs/hybrid/BROWSER_CLEANUP.md. */
export const PROFILE_PREFIX = "qa-again-playwright-";

const REGISTRY_DIR = join(tmpdir(), "qa-again-playwright-registry");

/** A registry entry older than this is treated as abandoned (its owning
 * process crashed without running its `finally`/signal-handler cleanup)
 * and no longer counts against the concurrency limit -- otherwise one
 * crashed run would permanently jam every future launch. Real cleanup
 * of the leftover process/profile is still the operator script's job. */
const STALE_ENTRY_MS = 30 * 60 * 1000;

const DEFAULT_MAX_CONCURRENT = 3;

function ensureRegistryDir(): void {
  mkdirSync(REGISTRY_DIR, { recursive: true });
}

function registryFilePath(runId: string): string {
  return join(REGISTRY_DIR, `${runId}.json`);
}

interface RegistryEntry {
  runId: string;
  userDataDir: string;
  label: string;
  launchedAt: string;
  pid: number | null;
}

function listLiveRegistryEntries(): RegistryEntry[] {
  ensureRegistryDir();
  const now = Date.now();
  const out: RegistryEntry[] = [];
  for (const file of readdirSync(REGISTRY_DIR)) {
    if (!file.endsWith(".json")) continue;
    try {
      const entry = JSON.parse(readFileSync(join(REGISTRY_DIR, file), "utf-8")) as RegistryEntry;
      if (now - new Date(entry.launchedAt).getTime() < STALE_ENTRY_MS) out.push(entry);
    } catch {
      // Unreadable/partial registry file -- ignore, it doesn't count
      // toward the concurrency limit either way.
    }
  }
  return out;
}

/** Blocks until fewer than `maxConcurrent` other QA-Again browsers are
 * tracked as active, so a retry storm or an operator starting several
 * runner/verification processes at once cannot open dozens of headed
 * browsers simultaneously. */
async function waitForConcurrencySlot(maxConcurrent: number): Promise<void> {
  // eslint-disable-next-line no-constant-condition
  while (true) {
    if (listLiveRegistryEntries().length < maxConcurrent) return;
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
}

export interface BrowserRunHandle {
  runId: string;
  userDataDir: string;
  context: BrowserContext;
  /** Convenience: the first page opened in the persistent context. */
  page: Page;
  /** Idempotent -- safe to call multiple times (including from a signal
   * handler racing the caller's own `finally`). Closes in order: page,
   * then persistent context. There is deliberately no separate
   * `browser.close()` -- `launchPersistentContext` does not return a
   * `Browser`, and assuming one exists is exactly the bug this fixes. */
  close(): Promise<void>;
}

const activeRuns = new Set<BrowserRunHandle>();
let signalHandlersRegistered = false;

function registerSignalHandlersOnce(): void {
  if (signalHandlersRegistered) return;
  signalHandlersRegistered = true;

  const closeAllTrackedRuns = async (): Promise<void> => {
    const runs = [...activeRuns];
    await Promise.all(
      runs.map((run) =>
        run.close().catch((err) => {
          console.error(`[browserRun] cleanup failed for run ${run.runId}:`, err);
        }),
      ),
    );
  };

  const handleSignal = (signal: NodeJS.Signals, exitCode: number) => {
    process.once(signal, () => {
      console.error(`[browserRun] ${signal} received -- closing ${activeRuns.size} tracked browser run(s) before exit`);
      closeAllTrackedRuns().finally(() => process.exit(exitCode));
    });
  };
  handleSignal("SIGINT", 130);
  handleSignal("SIGTERM", 143);

  process.on("uncaughtException", (err) => {
    console.error("[browserRun] uncaughtException -- closing tracked browser run(s) before exit:", err);
    closeAllTrackedRuns().finally(() => process.exit(1));
  });
  process.on("unhandledRejection", (reason) => {
    console.error("[browserRun] unhandledRejection -- closing tracked browser run(s) before exit:", reason);
    closeAllTrackedRuns().finally(() => process.exit(1));
  });
}

export interface LaunchTrackedBrowserOpts {
  /** Short human-readable tag folded into the run id / profile dir name,
   * e.g. "execute-run42", "record-session7", "verify-quick-manual-test". */
  label: string;
  headless?: boolean;
  slowMo?: number;
  /** Extra Chromium launch args (e.g. --load-extension for HYB-3
   * verification). --user-data-dir is always supplied by this helper
   * and must not be passed here. */
  args?: string[];
  /** Caps concurrently-active QA-Again browsers process-wide. Override
   * via QA_AGAIN_MAX_CONCURRENT_BROWSERS for CI/local tuning. */
  maxConcurrent?: number;
}

/** Launches one QA-Again-owned, uniquely-profiled, tracked headed (or
 * headless) Chromium instance via launchPersistentContext -- the only
 * Playwright API that lets us pin a named, discoverable user-data-dir.
 * Registers the run's PID/profile-dir in a small JSON registry (used by
 * both the concurrency limiter and the operator cleanup scripts) and
 * installs process-wide signal/exception handlers exactly once so ANY
 * tracked run still gets closed on Ctrl+C, SIGTERM, an uncaught
 * exception, or an unhandled rejection -- not just on a normal return
 * or a caught error inside the caller's own try/finally. */
export async function launchTrackedBrowser(opts: LaunchTrackedBrowserOpts): Promise<BrowserRunHandle> {
  registerSignalHandlersOnce();

  const maxConcurrent = opts.maxConcurrent ?? Number(process.env.QA_AGAIN_MAX_CONCURRENT_BROWSERS ?? DEFAULT_MAX_CONCURRENT);
  await waitForConcurrencySlot(maxConcurrent);

  const safeLabel = opts.label.replace(/[^a-zA-Z0-9._-]/g, "-");
  const runId = `${safeLabel}-${Date.now()}-${randomBytes(4).toString("hex")}`;
  const userDataDir = join(tmpdir(), `${PROFILE_PREFIX}${runId}`);
  mkdirSync(userDataDir, { recursive: true });

  const context = await chromium.launchPersistentContext(userDataDir, {
    headless: opts.headless ?? false,
    slowMo: opts.slowMo,
    args: opts.args ?? [],
  });

  ensureRegistryDir();
  const entry: RegistryEntry = {
    runId,
    userDataDir,
    label: opts.label,
    launchedAt: new Date().toISOString(),
    // launchPersistentContext does not expose the underlying process --
    // the registry/cleanup scripts identify owned OS processes by
    // matching --user-data-dir=<userDataDir> in the command line
    // instead (see runner/scripts/cleanup-qa-again-browsers.*).
    pid: null,
  };
  writeFileSync(registryFilePath(runId), JSON.stringify(entry, null, 2));

  const page = context.pages()[0] ?? (await context.newPage());

  let closed = false;
  const handle: BrowserRunHandle = {
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
        console.error(`[browserRun] run ${runId}: page.close() failed (continuing cleanup):`, err);
      }
      try {
        await context.close();
      } catch (err) {
        console.error(`[browserRun] run ${runId}: context.close() failed (continuing cleanup):`, err);
      }
      try {
        unlinkSync(registryFilePath(runId));
      } catch {
        // already removed, or never fully written -- fine either way.
      }
      try {
        rmSync(userDataDir, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
      } catch (err) {
        console.error(`[browserRun] run ${runId}: failed to remove profile dir ${userDataDir} (may need operator cleanup):`, err);
      }
    },
  };
  activeRuns.add(handle);
  return handle;
}

/** Acceptance-check helper: true if no trace (registry entry or profile
 * directory) of `runId` remains on disk. Does not check OS process
 * liveness for the persistent-context case (no PID is available); the
 * operator cleanup scripts do that by user-data-dir command-line match. */
export function isRunFullyCleanedUp(runId: string, userDataDir: string): boolean {
  return !existsSync(registryFilePath(runId)) && !existsSync(userDataDir);
}
