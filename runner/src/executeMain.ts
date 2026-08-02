import { loadConfig } from "./env.js";
import { claimAndExecuteOnce } from "./execution/executor.js";

// HYB-2 entry point: claims and executes exactly one queued
// WorkflowRun, then exits. Distinct from main.ts (the HYB-0 spike,
// untouched) -- `npm run execute` vs `npm run spike`.
//
// `--watch` (or `npm run execute:watch`): loops claimAndExecuteOnce()
// forever instead of exiting after one run -- a non-technical operator
// starts this once (see start-runner.ps1/.bat) and leaves it running,
// rather than having to notice a run is QUEUED and manually re-invoke
// `npm run execute` for every single one. Same per-run behavior either
// way; watch mode only changes whether the process exits afterward. A
// single run throwing (e.g. a transient network error) is logged and
// the loop continues -- it must not take the whole watcher down.
const config = loadConfig();
const headless = process.env.RUNNER_HEADLESS === "1";
const watch = process.argv.includes("--watch");

async function runOnce(): Promise<void> {
  const result = await claimAndExecuteOnce(config, { headless });
  if (!result) {
    console.log("[runner] nothing to execute this cycle");
    return;
  }
  console.log(
    `[runner] finalStatus=${result.finalStatus} pausedAtCheckpoint=${result.pausedAtCheckpoint} resumedFromCheckpoint=${result.resumedFromCheckpoint}`,
  );
}

if (watch) {
  console.log("[runner] watch mode -- claiming runs continuously until stopped (Ctrl+C to exit)");
  // eslint-disable-next-line no-constant-condition
  while (true) {
    try {
      await runOnce();
    } catch (err) {
      console.error("[runner] execution failed (continuing to watch):", err);
    }
  }
} else {
  runOnce()
    .then(() => console.log("[runner] exiting -- single-run mode (pass --watch to keep running)"))
    .catch((err) => {
      console.error("[runner] execution failed:", err);
      process.exitCode = 1;
    });
}
