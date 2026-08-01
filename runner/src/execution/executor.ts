import { chromium, type Browser, type Page } from "playwright";
import type { RunnerConfig } from "../env.js";
import { WorkflowRunClient, type ClaimedRun, type ClaimedStep } from "../api/executionClient.js";
import { resolveLocator, resolveValue, categorizeError } from "./locators.js";

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
  finalStatus: "PASSED" | "FAILED" | "CANCELLED";
  pausedAtCheckpoint: boolean;
}

export async function executeClaimedRun(
  client: WorkflowRunClient,
  claimed: Required<Pick<ClaimedRun, "run" | "steps" | "lease_token">> & { target_base_url?: string | null },
  config: RunnerConfig,
  opts: { headless?: boolean } = {},
): Promise<ExecuteRunResult> {
  const runId = claimed.run.id;
  const leaseToken = claimed.lease_token;

  const browser: Browser = await chromium.launch({ headless: opts.headless ?? false, slowMo: opts.headless ? 0 : 150 });
  let finalStatus: "PASSED" | "FAILED" | "CANCELLED" = "PASSED";
  let pausedAtCheckpoint = false;

  try {
    const page = await browser.newPage();

    for (const step of claimed.steps) {
      // Cooperative cancellation -- checked before every step, not just once.
      const current = await client.getRun(runId);
      if (current.cancel_requested) {
        console.log(`[runner] run ${runId}: cancel_requested observed -- stopping before step ${step.sequence_no}`);
        finalStatus = "CANCELLED";
        break;
      }

      await client.heartbeat(runId, leaseToken);

      if (step.step_type === "MANUAL_CHECKPOINT") {
        console.log(`[runner] run ${runId}: reached MANUAL_CHECKPOINT at step ${step.sequence_no} -- pausing (resume is HYB-4 scope)`);
        await client.postEvent(runId, leaseToken, "CHECKPOINT_WAITING", {
          payload: { step_id: step.id, instructions: step.checkpoint_instructions },
        });
        pausedAtCheckpoint = true;
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
        break;
      }
    }

    if (!pausedAtCheckpoint) {
      await client.complete(runId, leaseToken, finalStatus);
      console.log(`[runner] run ${runId}: complete (${finalStatus})`);
    }
  } finally {
    await browser.close();
  }

  return { finalStatus, pausedAtCheckpoint };
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
