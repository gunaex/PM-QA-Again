import { chromium, type Browser, type Page } from "playwright";
import type { RunnerConfig } from "../env.js";
import { RecordingSessionClient } from "../api/recordingClient.js";
import { RECORDER_INIT_SCRIPT } from "./domRecorder.js";
import { resolveLocator } from "../execution/locators.js";
import type { ClaimedStep } from "../api/executionClient.js";

interface RecorderEmittedEvent {
  stepType: string;
  pageContext: string;
  locatorStrategy?: string;
  locatorValue?: string;
  locatorFallbacks?: Array<{ strategy: string; value: string }>;
  locatorWarnings?: string[];
  targetSummary?: string;
  diagnosticX?: number;
  diagnosticY?: number;
  inputValue?: string;
  isSensitive?: boolean;
  checkpointInstructions?: string;
  needsReview?: boolean;
  reviewNote?: string;
}

const ACTIVE_STATUSES = new Set(["RECORDING", "PAUSED"]);

/** Claims and runs exactly one recording session to completion (STOPPED,
 * DISCARDED, or lease loss), then returns. A tester controls it
 * remotely via the QA-Again frontend (pause/resume/stop/discard/insert
 * checkpoint) while this process does the actual browser work. */
export async function claimAndRecordOnce(
  config: RunnerConfig,
  opts: { pollIntervalMs?: number; maxAttempts?: number; headless?: boolean; debugPort?: number } = {},
): Promise<{ recorded: boolean; sessionId?: number; finalStatus?: string }> {
  const client = new RecordingSessionClient(config);
  const pollIntervalMs = opts.pollIntervalMs ?? 1500;
  const maxAttempts = opts.maxAttempts ?? 20;

  let claimed;
  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    claimed = await client.claim();
    if (claimed.claimed) break;
    await new Promise((resolve) => setTimeout(resolve, pollIntervalMs));
  }
  if (!claimed?.claimed || !claimed.session || !claimed.lease_token) {
    console.log("[recorder] no queued recording session appeared within the polling window");
    return { recorded: false };
  }

  const sessionId = claimed.session.id;
  const leaseToken = claimed.lease_token;
  const targetUrl = claimed.session.target_url;
  console.log(`[recorder] claimed recording session ${sessionId} -> ${targetUrl}`);

  // debugPort is opt-in and local-only (loopback CDP endpoint) -- lets a
  // separate process attach to this exact same browser window to drive
  // it (used for automated verification of the recorder; a human tester
  // normally just uses the window directly, no debug port needed).
  const launchArgs = opts.debugPort ? [`--remote-debugging-port=${opts.debugPort}`] : [];
  const browser: Browser = await chromium.launch({ headless: opts.headless ?? false, slowMo: opts.headless ? 0 : 50, args: launchArgs });
  let lastEmittedNavUrl: string | null = null;
  let localPaused = false;

  // Click events reach Node via the in-page exposeFunction bridge;
  // NAVIGATE events reach Node via Playwright's own framenavigated
  // listener -- two genuinely independent async sources. Without a
  // shared queue, whichever one's network POST happens to complete
  // first wins, which does not necessarily match the true order the
  // events occurred in (e.g. a click that triggers a navigation was
  // sometimes persisted AFTER the resulting NAVIGATE). This single
  // Node-side FIFO chain, shared by both sources, ensures each
  // append-step call fully completes before the next one (from either
  // source) begins. Found via this session's real recording, not by
  // inspection.
  let appendQueue: Promise<unknown> = Promise.resolve();
  const enqueueAppend = (fn: () => Promise<void>) => {
    appendQueue = appendQueue.then(fn, fn);
    return appendQueue;
  };

  try {
    const page: Page = await browser.newPage();

    await page.exposeFunction("__qaRecorderEmit", (event: RecorderEmittedEvent) =>
      enqueueAppend(async () => {
      try {
        await client.appendStep(sessionId, leaseToken, {
          step_type: event.stepType,
          description: null,
          locator_strategy: event.locatorStrategy ?? null,
          locator_value: event.locatorValue ?? null,
          locator_fallbacks_json: event.locatorFallbacks ? JSON.stringify(event.locatorFallbacks) : null,
          locator_warnings_json: event.locatorWarnings && event.locatorWarnings.length ? JSON.stringify(event.locatorWarnings) : null,
          target_summary: event.targetSummary ?? null,
          page_context: event.pageContext ?? null,
          diagnostic_x: event.diagnosticX ?? null,
          diagnostic_y: event.diagnosticY ?? null,
          // event.inputValue is `undefined` (not merely falsy) for a
          // sensitive field -- domRecorder.ts never sets it in that
          // case, so there is nothing secret in this payload to begin
          // with, in this process or on the wire.
          input_value: event.inputValue ?? null,
          is_sensitive: !!event.isSensitive,
          checkpoint_instructions: event.checkpointInstructions ?? null,
          needs_review: !!event.needsReview,
          review_note: event.reviewNote ?? null,
        });
        console.log(`[recorder] captured ${event.stepType}${event.locatorValue ? ` (${event.locatorStrategy}=${event.locatorValue})` : ""}`);
      } catch (err) {
        // A capture failing to persist must not crash the recording
        // session -- log it loudly and keep going; the tester will see
        // a gap in the step list and can re-do the action if needed.
        console.error("[recorder] failed to record a captured step:", err);
      }
      }),
    );

    await page.addInitScript(RECORDER_INIT_SCRIPT);

    page.on("framenavigated", (frame) => {
      if (frame !== page.mainFrame()) return;
      const url = frame.url();
      if (url === "about:blank" || url === lastEmittedNavUrl || localPaused) return;
      lastEmittedNavUrl = url;
      enqueueAppend(async () => {
        try {
          await client.appendStep(sessionId, leaseToken, {
            step_type: "NAVIGATE",
            input_value: url,
            page_context: new URL(url).pathname,
          });
          console.log(`[recorder] captured NAVIGATE ${url}`);
        } catch (err) {
          console.error("[recorder] failed to record NAVIGATE:", err);
        }
      });
    });

    // Mark RECORDING before the initial navigation -- otherwise the
    // very first NAVIGATE (fired by this goto itself) races the
    // session's still-CLAIMED status and the backend correctly rejects
    // it (append-step requires RECORDING). Real bug, found via this
    // actual end-to-end run, not code review.
    await client.markStarted(sessionId, leaseToken);
    await page.goto(targetUrl);
    lastEmittedNavUrl = targetUrl;
    console.log(`[recorder] recording started -- interact with the browser window; control it from the QA-Again UI`);

    // Poll loop: heartbeat, react to pause/resume/stop/discard, and
    // service any pending "test this locator" requests using the exact
    // same resolveLocator() code path replay (HYB-2) uses.
    let finalStatus = "STOPPED";
    while (true) {
      await new Promise((resolve) => setTimeout(resolve, pollIntervalMs));
      let detail;
      try {
        detail = await client.heartbeat(sessionId, leaseToken);
      } catch (err) {
        console.error("[recorder] heartbeat failed (lease likely lost):", err);
        finalStatus = "RUNNER_LOST";
        break;
      }

      const shouldPause = detail.status === "PAUSED";
      if (shouldPause !== localPaused) {
        localPaused = shouldPause;
        await page.evaluate((paused) => {
          (window as unknown as { __qaRecorderPaused: boolean }).__qaRecorderPaused = paused;
        }, localPaused);
        console.log(`[recorder] recording ${localPaused ? "paused" : "resumed"} (tester action)`);
      }

      if (!ACTIVE_STATUSES.has(detail.status)) {
        finalStatus = detail.status;
        console.log(`[recorder] session ended (status=${finalStatus}) -- closing browser`);
        break;
      }

      // Service pending locator-test requests.
      try {
        const pending = await client.pendingLocatorTests(sessionId, leaseToken);
        for (const step of pending) {
          const claimedStep = {
            id: step.id,
            locator_strategy: step.locator_strategy,
            locator_value: step.locator_value,
          } as unknown as ClaimedStep;
          try {
            const locator = resolveLocator(page, claimedStep);
            const count = await locator.count();
            await client.submitLocatorTestResult(sessionId, step.id, leaseToken, {
              matchedCount: count,
              ok: count === 1,
              message: count === 0 ? "No matching element found on the current page." : count > 1 ? `Matched ${count} elements -- not unique.` : undefined,
            });
          } catch (err) {
            await client.submitLocatorTestResult(sessionId, step.id, leaseToken, {
              matchedCount: 0,
              ok: false,
              message: String((err as Error)?.message ?? err),
            });
          }
        }
      } catch (err) {
        console.error("[recorder] failed to service pending locator tests:", err);
      }
    }

    return { recorded: true, sessionId, finalStatus };
  } finally {
    await browser.close();
  }
}
