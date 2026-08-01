import { loadConfig } from "./env.js";
import { claimAndExecuteOnce } from "./execution/executor.js";

// HYB-2 entry point: claims and executes exactly one queued
// WorkflowRun, then exits. Distinct from main.ts (the HYB-0 spike,
// untouched) -- `npm run execute` vs `npm run spike`. A long-lived
// runner service would loop claimAndExecuteOnce() forever instead of
// exiting after one run; kept bounded here so it's simple to invoke
// from a CI step or a one-shot verification run.
const config = loadConfig();
const headless = process.env.RUNNER_HEADLESS === "1";

claimAndExecuteOnce(config, { headless })
  .then((result) => {
    if (!result) {
      console.log("[runner] exiting -- nothing to execute");
      return;
    }
    console.log(`[runner] exiting -- finalStatus=${result.finalStatus} pausedAtCheckpoint=${result.pausedAtCheckpoint}`);
  })
  .catch((err) => {
    console.error("[runner] execution failed:", err);
    process.exitCode = 1;
  });
