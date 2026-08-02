import type { Page } from "playwright";
import type { RunnerConfig } from "../env.js";
import { WorkflowRunClient, type ClaimedRun, type ClaimedStep, type RunDetail } from "../api/executionClient.js";
import { resolveLocator, resolveValue, categorizeError } from "./locators.js";
import { launchTrackedBrowser } from "../browser/browserRun.js";

async function pollUntil(check: () => Promise<boolean>, timeoutMs: number, failureMessage: string, intervalMs = 200): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await check()) return;
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
  if (await check()) return;
  throw new Error(failureMessage);
}

/** Executes one step against a persistent browser session -- the same
 * `page` object is reused across every step in a run (and would remain
 * alive across a MANUAL_CHECKPOINT pause too, once HYB-4 builds the
 * resume side; HYB-2 stops cleanly at a checkpoint rather than faking
 * a resume it doesn't yet implement). */
async function executeStep(page: Page, step: ClaimedStep, targetBaseUrl: string | null): Promise<{ locatorUsedJson?: string }> {
  const timeout = step.timeout_ms ?? 15000;
  switch (step.step_type) {
    case "NAVIGATE": {
      const url = resolveValue(step);
      const target = /^https?:\/\//.test(url) ? url : `${targetBaseUrl ?? ""}${url}`;
      await page.goto(target, { timeout });
      return {};
    }
    case "CLICK": {
      const locator = resolveLocator(page, step);
      await locator.click({ timeout });
      return { locatorUsedJson: JSON.stringify({ strategy: step.locator_strategy, value: step.locator_value }) };
    }
    case "FILL": {
      const locator = resolveLocator(page, step);
      await locator.fill(resolveValue(step), { timeout });
      return { locatorUsedJson: JSON.stringify({ strategy: step.locator_strategy, value: step.locator_value }) };
    }
    case "SELECT": {
      const locator = resolveLocator(page, step);
      await locator.selectOption(resolveValue(step), { timeout });
      return { locatorUsedJson: JSON.stringify({ strategy: step.locator_strategy, value: step.locator_value }) };
    }
    case "CHECK": {
      const locator = resolveLocator(page, step);
      await locator.check({ timeout });
      return {};
    }
    case "UNCHECK": {
      const locator = resolveLocator(page, step);
      await locator.uncheck({ timeout });
      return {};
    }
    case "PRESS_KEY": {
      if (step.locator_strategy) {
        await resolveLocator(page, step).press(step.input_value ?? "Enter", { timeout });
      } else {
        await page.keyboard.press(step.input_value ?? "Enter");
      }
      return {};
    }
    case "WAIT_FOR_ELEMENT": {
      await resolveLocator(page, step).waitFor({ state: "visible", timeout });
      return {};
    }
    case "ASSERT_VISIBLE": {
      const locator = resolveLocator(page, step);
      const visible = await locator.isVisible();
      if (!visible) throw new Error(`Expected element to be visible: ${step.locator_strategy}=${step.locator_value}`);
      return {};
    }
    case "ASSERT_TEXT": {
      // Auto-retries within the step timeout -- a page that's still
      // navigating/rendering right after a preceding CLICK/NAVIGATE is
      // not yet a real assertion failure, matching how Playwright's own
      // expect() assertions auto-wait rather than checking exactly once.
      await pollUntil(
        async () => {
          const body = await page.textContent("body");
          return !!body && body.includes(step.expected_value ?? "");
        },
        timeout,
        `Expected page text to include "${step.expected_value}"`,
      );
      return {};
    }
    case "ASSERT_URL": {
      await pollUntil(
        async () => !step.expected_value || page.url().includes(step.expected_value),
        timeout,
        `Expected URL to include "${step.expected_value}", got "${page.url()}"`,
      );
      return {};
    }
    case "SCREENSHOT":
      return {}; // handled by the caller, which needs client/run context to upload
    case "MANUAL_CHECKPOINT":
      return {}; // handled by the caller -- pauses the run, does not execute further
    default:
      throw new Error(`Unsupported step_type: ${step.step_type}`);
  }
}

export interface ExecuteRunResult {
  finalStatus: "PASSED" | "FAILED" | "CANCELLED" | "BLOCKED" | "NOT_APPLICABLE" | "RUNNER_LOST";
  /** True if the run entered WAITING_FOR_HUMAN at least once during this
   * execution -- distinct from finalStatus, since a checkpoint can be
   * PASSed and fully resumed (pausedAtCheckpoint=true, finalStatus=
   * PASSED) just as honestly as it can end the run right there. */
  pausedAtCheckpoint: boolean;
  /** True only when a PASS decision was observed and execution actually
   * continued past the checkpoint in the *same* browser session. */
  resumedFromCheckpoint: boolean;
}

type CheckpointOutcome =
  | { kind: "resumed"; steps: ClaimedStep[] }
  | { kind: "cancelled" }
  | { kind: "terminal"; status: string }
  | { kind: "browser-lost" };

/** HYB-4: polls while a run sits WAITING_FOR_HUMAN, keeping the lease
 * alive via heartbeat every cycle -- exactly the "continue heartbeat and
 * lease renewal while paused" requirement. Never assumes a resume; only
 * returns `resumed` once the server has actually confirmed a PASS
 * decision and handed back the remaining steps via /checkpoint-resume.
 * A transient network error while polling is logged and retried, not
 * treated as loss -- the server's own paused-lease grace window
 * (PAUSED_LEASE_DURATION_SECONDS) is what actually decides staleness. */
async function waitForHumanDecision(
  client: WorkflowRunClient,
  runId: number,
  leaseToken: string,
  workflowStepId: number,
  page: Page,
  pollIntervalMs: number,
): Promise<CheckpointOutcome> {
  const terminalStatuses = new Set(["FAILED", "BLOCKED", "NOT_APPLICABLE", "CANCELLED", "RUNNER_LOST"]);

  // eslint-disable-next-line no-constant-condition
  while (true) {
    await new Promise((resolve) => setTimeout(resolve, pollIntervalMs));

    if (page.isClosed()) {
      console.error(`[runner] run ${runId}: the Playwright page closed unexpectedly while paused -- reporting honestly, not fabricating a resume`);
      return { kind: "browser-lost" };
    }

    let current: RunDetail;
    try {
      current = await client.getRun(runId);
    } catch (err) {
      console.warn(`[runner] run ${runId}: poll failed while paused (transient network loss?) -- retrying: ${(err as Error).message}`);
      continue;
    }

    if (current.cancel_requested) {
      return { kind: "cancelled" };
    }

    if (current.status === "RESUMING") {
      try {
        const resumed = await client.resumeCheckpoint(runId, leaseToken, workflowStepId);
        console.log(`[runner] run ${runId}: checkpoint decision=${resumed.decision.status} -- resuming the same browser session with ${resumed.steps.length} remaining step(s)`);
        return { kind: "resumed", steps: resumed.steps };
      } catch (err) {
        console.error(`[runner] run ${runId}: /checkpoint-resume failed, will retry on next poll: ${(err as Error).message}`);
        continue;
      }
    }

    if (terminalStatuses.has(current.status)) {
      // A human FAIL/BLOCKED/NOT_APPLICABLE decision (or the server's own
      // lease sweep) already finalized the run server-side -- nothing to
      // execute, nothing for this runner to call.
      return { kind: "terminal", status: current.status };
    }

    try {
      await client.heartbeat(runId, leaseToken);
    } catch (err) {
      console.warn(`[runner] run ${runId}: heartbeat failed while paused -- retrying: ${(err as Error).message}`);
    }
  }
}

export async function executeClaimedRun(
  client: WorkflowRunClient,
  claimed: Required<Pick<ClaimedRun, "run" | "steps" | "lease_token">> & { target_base_url?: string | null },
  config: RunnerConfig,
  opts: { headless?: boolean; checkpointPollIntervalMs?: number } = {},
): Promise<ExecuteRunResult> {
  const runId = claimed.run.id;
  const leaseToken = claimed.lease_token;
  const checkpointPollIntervalMs = opts.checkpointPollIntervalMs ?? 3000;

  const run = await launchTrackedBrowser({
    label: `execute-run${runId}`,
    headless: opts.headless ?? false,
    slowMo: opts.headless ? 0 : 150,
  });
  let finalStatus: ExecuteRunResult["finalStatus"] = "PASSED";
  let pausedAtCheckpoint = false;
  let resumedFromCheckpoint = false;
  // Once true, the run was already finalized by the checkpoint-decision
  // endpoint (or this runner's own RUNNER_LOST self-report) -- calling
  // /complete again would be either redundant or outright rejected
  // (lease already cleared), so the final /complete call is skipped.
  let alreadyFinalizedServerSide = false;

  try {
    const page = run.page;
    let steps: ClaimedStep[] = claimed.steps;
    let stopped = false;

    while (steps.length > 0 && !stopped) {
      const step = steps[0];
      steps = steps.slice(1);

      // Cooperative cancellation -- checked before every step, not just once.
      const current = await client.getRun(runId);
      if (current.cancel_requested) {
        console.log(`[runner] run ${runId}: cancel_requested observed -- stopping before step ${step.sequence_no}`);
        finalStatus = "CANCELLED";
        stopped = true;
        break;
      }

      await client.heartbeat(runId, leaseToken);

      if (step.step_type === "MANUAL_CHECKPOINT") {
        console.log(`[runner] run ${runId}: reached MANUAL_CHECKPOINT at step ${step.sequence_no} -- pausing, keeping the browser session alive`);
        pausedAtCheckpoint = true;

        // 1. Finish and persist all prior automated step results -- already
        // true by construction (every earlier step's finishStepRun already
        // landed before this iteration).
        // 2-4. Create this checkpoint's own step-run row, capture the
        // current page state, and upload it as RUNNER-sourced evidence --
        // gives the human reviewer a real screenshot + URL/title, and gives
        // the checkpoint decision a workflow_step_run_id to attach to.
        const { id: checkpointStepRunId } = await client.startStepRun(runId, leaseToken, step.id);
        try {
          const screenshotBuffer = await page.screenshot();
          await client.uploadEvidence(runId, leaseToken, checkpointStepRunId, screenshotBuffer, `run-${runId}-checkpoint-${step.sequence_no}.png`);
        } catch (evErr) {
          console.error(`[runner] run ${runId}: failed to capture/upload the checkpoint screenshot (continuing to pause regardless): ${(evErr as Error).message}`);
        }

        const url = page.url();
        const title = await page.title().catch(() => null);
        await client.postEvent(runId, leaseToken, "CHECKPOINT_WAITING", {
          payload: { step_id: step.id, instructions: step.checkpoint_instructions, url, title },
        });

        // 5-6. Transition to WAITING_FOR_HUMAN already happened server-side
        // via the event above. Continue heartbeat/lease renewal and poll
        // for the accepted decision.
        const outcome = await waitForHumanDecision(client, runId, leaseToken, step.id, page, checkpointPollIntervalMs);

        if (outcome.kind === "resumed") {
          resumedFromCheckpoint = true;
          steps = outcome.steps; // exact remaining steps, same page/browser continues
          continue;
        }
        if (outcome.kind === "cancelled") {
          finalStatus = "CANCELLED";
          stopped = true;
          break;
        }
        if (outcome.kind === "terminal") {
          finalStatus = outcome.status as ExecuteRunResult["finalStatus"];
          alreadyFinalizedServerSide = true;
          stopped = true;
          break;
        }
        // outcome.kind === "browser-lost": honest self-report, never a
        // fabricated continuation.
        finalStatus = "RUNNER_LOST";
        try {
          await client.complete(runId, leaseToken, "RUNNER_LOST", "Chromium session was lost while paused at a checkpoint");
          alreadyFinalizedServerSide = true;
        } catch (err) {
          console.error(`[runner] run ${runId}: could not even self-report RUNNER_LOST (lease likely already expired server-side, which is also honest): ${(err as Error).message}`);
          alreadyFinalizedServerSide = true;
        }
        stopped = true;
        break;
      }

      console.log(`[runner] run ${runId}: step ${step.sequence_no} (${step.step_type}) starting`);
      const { id: stepRunId } = await client.startStepRun(runId, leaseToken, step.id);

      try {
        const { locatorUsedJson } = await executeStep(page, step, claimed.target_base_url ?? null);

        if (step.step_type === "SCREENSHOT") {
          const screenshotBuffer = await page.screenshot();
          await client.uploadEvidence(runId, leaseToken, stepRunId, screenshotBuffer, `run-${runId}-step-${step.sequence_no}.png`);
        }

        await client.finishStepRun(runId, stepRunId, leaseToken, { status: "PASSED", locatorUsedJson });
        console.log(`[runner] run ${runId}: step ${step.sequence_no} PASSED`);
      } catch (err) {
        const category = categorizeError(step.step_type, err);
        const message = String((err as Error)?.message ?? err);
        await client.finishStepRun(runId, stepRunId, leaseToken, {
          status: "FAILED",
          failureCategory: category,
          machineMessage: step.is_sensitive ? `${category} (message withheld -- sensitive step)` : message,
        });
        console.log(`[runner] run ${runId}: step ${step.sequence_no} FAILED (${category})`);
        finalStatus = "FAILED";
        stopped = true;
        break;
      }
    }

    if (!alreadyFinalizedServerSide) {
      await client.complete(runId, leaseToken, finalStatus as "PASSED" | "FAILED" | "BLOCKED" | "SYSTEM_ERROR" | "CANCELLED" | "RUNNER_LOST");
      console.log(`[runner] run ${runId}: complete (${finalStatus})`);
    } else {
      console.log(`[runner] run ${runId}: already finalized server-side (${finalStatus}) -- not calling /complete again`);
    }
  } finally {
    await run.close();
  }

  return { finalStatus, pausedAtCheckpoint, resumedFromCheckpoint };
}

/** Polls /claim until a run is available (or attempts run out), executes
 * it, then returns. Used by executeMain.ts for a single bounded
 * execution -- a long-lived runner process would instead loop this
 * forever. */
export async function claimAndExecuteOnce(
  config: RunnerConfig,
  opts: { pollIntervalMs?: number; maxAttempts?: number; headless?: boolean } = {},
): Promise<ExecuteRunResult | null> {
  const client = new WorkflowRunClient(config);
  const pollIntervalMs = opts.pollIntervalMs ?? 2000;
  const maxAttempts = opts.maxAttempts ?? 15;

  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    const claimed = await client.claim();
    if (claimed.claimed && claimed.run && claimed.steps && claimed.lease_token) {
      console.log(`[runner] claimed run ${claimed.run.id} (${claimed.steps.length} steps)`);
      return executeClaimedRun(
        client,
        { run: claimed.run, steps: claimed.steps, lease_token: claimed.lease_token, target_base_url: claimed.target_base_url },
        config,
        { headless: opts.headless },
      );
    }
    await new Promise((resolve) => setTimeout(resolve, pollIntervalMs));
  }
  console.log("[runner] no queued run appeared within the polling window");
  return null;
}
