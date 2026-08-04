// Acceptance check for the headed-Chrome cleanup fix: runs three real
// browser scenarios (success, deliberate failure, cancellation/timeout)
// through the shared launchTrackedBrowser() lifecycle and confirms zero
// QA-Again-owned processes/profile directories remain after each one.
//
// This does not require the QA-Again backend/frontend to be running --
// it exercises the lifecycle helper itself (launch, use, close-on-every-
// path), which is exactly the code executor.ts/recordSession.ts/spike.ts
// and both verify-*.mjs scripts share. Real headed Chromium windows will
// briefly appear.
//
// Usage: node verify-browser-cleanup.mjs
import { launchTrackedBrowser, listOwnedRegistryEntries, isRunFullyCleanedUp } from "./lib/browserLifecycle.mjs";

function assertZeroOwnedProcesses(label) {
  const live = listOwnedRegistryEntries();
  if (live.length !== 0) {
    throw new Error(`[${label}] expected zero QA-Again-owned browser registry entries, found ${live.length}: ${JSON.stringify(live)}`);
  }
  console.log(`  [${label}] PASS: zero QA-Again-owned browser processes remain`);
}

async function scenarioSuccess() {
  console.log("\nScenario 1: successful run (page.close -> context.close -> profile removed)...");
  const run = await launchTrackedBrowser({ label: "acceptance-success" });
  try {
    await run.page.goto("about:blank");
    await run.page.evaluate(() => document.title);
  } finally {
    await run.close();
  }
  if (!isRunFullyCleanedUp(run.runId, run.userDataDir)) {
    throw new Error(`[success] registry entry or profile dir for ${run.runId} still present after close()`);
  }
  assertZeroOwnedProcesses("success");
}

async function scenarioFailure() {
  console.log("\nScenario 2: deliberate assertion failure mid-run (must still clean up via finally)...");
  const run = await launchTrackedBrowser({ label: "acceptance-failure" });
  let threw = false;
  try {
    await run.page.goto("about:blank");
    throw new Error("deliberate failure injected by verify-browser-cleanup.mjs");
  } catch (err) {
    threw = true;
    console.log(`  (expected) caught: ${err.message}`);
  } finally {
    await run.close();
  }
  if (!threw) throw new Error("[failure] scenario did not actually throw -- test is broken");
  if (!isRunFullyCleanedUp(run.runId, run.userDataDir)) {
    throw new Error(`[failure] registry entry or profile dir for ${run.runId} still present after close()`);
  }
  assertZeroOwnedProcesses("failure");
}

async function scenarioCancelledTimeout() {
  console.log("\nScenario 3: cancellation/timeout (abandon mid-action via Promise.race, must still clean up)...");
  const run = await launchTrackedBrowser({ label: "acceptance-cancel" });
  try {
    await run.page.goto("about:blank");
    // Simulates a step that hangs past its deadline -- the caller races
    // it against a short timeout and abandons the hung operation,
    // exactly like a real CANCELLED/timeout run would; the browser
    // still needs closing regardless of which side of the race won.
    await Promise.race([
      run.page.waitForSelector("#never-appears", { timeout: 60000 }).catch(() => {}),
      new Promise((resolve) => setTimeout(resolve, 300)),
    ]);
  } finally {
    await run.close();
  }
  if (!isRunFullyCleanedUp(run.runId, run.userDataDir)) {
    throw new Error(`[cancel] registry entry or profile dir for ${run.runId} still present after close()`);
  }
  assertZeroOwnedProcesses("cancel");
}

async function main() {
  const before = listOwnedRegistryEntries();
  console.log(`Baseline QA-Again-owned browser registry entries before test: ${before.length}`);
  if (before.length !== 0) {
    console.warn("WARNING: baseline is not zero -- a previous run may not have cleaned up. Continuing anyway.");
  }

  await scenarioSuccess();
  await scenarioFailure();
  await scenarioCancelledTimeout();

  console.log("\nALL BROWSER CLEANUP ACCEPTANCE CHECKS PASSED -- zero QA-Again-owned processes/profiles remained after success, failure, and cancellation.");
}

main().catch((err) => {
  console.error("BROWSER CLEANUP ACCEPTANCE CHECK FAILED:", err);
  process.exitCode = 1;
});
