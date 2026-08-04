import { loadConfig } from "./env.js";
import { claimAndRecordOnce } from "./recorder/recordSession.js";

// HYB-3 entry point: claims and runs exactly one queued
// RecordingSession, then exits. `npm run record` -- distinct from
// `npm run execute` (HYB-2) and `npm run spike` (HYB-0), both untouched.
const config = loadConfig();
const headless = process.env.RUNNER_HEADLESS === "1";
const debugPort = process.env.RECORDER_DEBUG_PORT ? Number(process.env.RECORDER_DEBUG_PORT) : undefined;

claimAndRecordOnce(config, { headless, debugPort })
  .then((result) => {
    if (!result.recorded) {
      console.log("[recorder] exiting -- nothing to record");
      return;
    }
    console.log(`[recorder] exiting -- session ${result.sessionId} ended with status ${result.finalStatus}`);
  })
  .catch((err) => {
    console.error("[recorder] recording failed:", err);
    process.exitCode = 1;
  });
