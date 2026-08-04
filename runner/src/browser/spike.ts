import { writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { RunnerConfig } from "../env.js";
import { QaAgainClient } from "../api/client.js";
import { launchTrackedBrowser } from "./browserRun.js";

/**
 * HYB-0 spike scenario, locked to exactly what
 * docs/hybrid/HYB-0-GAP-ANALYSIS.md decided:
 *
 *   Step 1: NAVIGATE to QA-Again's own /login page
 *   Step 2: FILL the email field (semantic locator: accessible label)
 *   Step 3: FILL the password field (semantic locator: accessible label)
 *   -> MANUAL_CHECKPOINT: pause before submitting, human decides
 *   -> on PASS: click "Sign in" (semantic locator: accessible role+name),
 *      wait for the Projects page, capture 1 screenshot, upload it,
 *      finish the run
 *   -> on anything else: stop, do NOT submit, do NOT report PASS
 *
 * No recorder, no workflow model, no AI — see gap analysis section 7 for
 * the full list of what HYB-0 deliberately excludes.
 */
export async function runSpike(config: RunnerConfig): Promise<void> {
  const client = new QaAgainClient(config);

  const run = await client.createRun("hyb0-spike-login-flow");
  console.log(`[runner] created run ${run.id} (status=${run.status})`);

  // headless: false — gate criterion 1: the browser must be actually
  // visible, not a headless process claiming to have "seen" something.
  const browserRun = await launchTrackedBrowser({ label: `spike-run${run.id}`, headless: false, slowMo: 300 });

  try {
    const page = browserRun.page;

    console.log("[runner] step 1: NAVIGATE");
    await client.postEvent(run.id, "STEP_STARTED", { step: 1, action: "NAVIGATE", target: "/login" });
    await page.goto(`${config.targetBaseUrl}/login`);
    await page.waitForSelector("text=QA-Again");
    await client.postEvent(run.id, "STEP_COMPLETED", { step: 1 });

    console.log("[runner] step 2: FILL email");
    await client.postEvent(run.id, "STEP_STARTED", { step: 2, action: "FILL", locator: "label:Email" });
    await page.getByLabel("Email").fill(config.targetEmail);
    await client.postEvent(run.id, "STEP_COMPLETED", { step: 2 });

    console.log("[runner] step 3: FILL password");
    await client.postEvent(run.id, "STEP_STARTED", { step: 3, action: "FILL", locator: "label:Password" });
    await page.getByLabel("Password").fill(config.targetPassword);
    await client.postEvent(run.id, "STEP_COMPLETED", { step: 3 });

    console.log(`[runner] checkpoint: waiting for a human decision on run ${run.id}`);
    console.log(
      `[runner]   POST ${config.backendBaseUrl}/api/${config.projectSlug}/hybrid/runs/${run.id}/checkpoint-decision`,
    );
    console.log('[runner]   body: {"decision":"PASS"}  (as a logged-in QA-Again user, e.g. via curl -b cookies.txt)');
    await client.postEvent(run.id, "CHECKPOINT_WAITING", {
      title: "Confirm login form is filled correctly before submitting",
      instruction: "Review the email/password fields, then approve to let the runner click Sign in.",
    });

    const resumed = await client.waitForHumanDecision(run.id);

    if (resumed.status !== "RESUMING") {
      console.log(`[runner] human decision was not PASS (run status: ${resumed.status}) — stopping, NOT submitting login`);
      console.log(`[runner]   decision: ${JSON.stringify(resumed.latest_decision)}`);
      return; // deliberately does not call finishRun — a non-PASS decision already ended the run
    }

    console.log("[runner] resumed — clicking Sign in");
    await client.postEvent(run.id, "STEP_STARTED", { step: 4, action: "CLICK", locator: "role:button[Sign in]" });
    await page.getByRole("button", { name: "Sign in" }).click();
    await page.waitForSelector('h1:has-text("Projects")', { timeout: 15000 });
    await client.postEvent(run.id, "STEP_COMPLETED", { step: 4 });

    console.log("[runner] capturing 1 screenshot");
    const screenshotPath = join(tmpdir(), `hyb0-run-${run.id}.png`);
    const screenshotBuffer = await page.screenshot();
    writeFileSync(screenshotPath, screenshotBuffer);
    await client.uploadEvidence(run.id, screenshotPath, `run-${run.id}-final.png`);
    console.log(`[runner] evidence uploaded (${screenshotPath})`);

    const finished = await client.finishRun(run.id);
    console.log(`[runner] run ${finished.id} finished with status ${finished.status}`);
  } finally {
    await browserRun.close();
  }
}
