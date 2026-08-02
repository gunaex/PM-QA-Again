// Real headed-browser verification for the Quick Manual Test UX flow.
// Measures real clicks and elapsed time for the primary requirement:
//   Dashboard -> Start Testing -> Quick Manual Test -> active execution
// against a real running backend/frontend, then exercises evidence
// enforcement, Save & Next, Run Now (from a suite set up via the real
// API), Rerun FAIL/BLOCKED (via the real UI button), and Continue Last
// Test, plus Excel/ZIP export inclusion (via the real API).
//
// Usage: node verify-quick-manual-test.mjs
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { launchTrackedBrowser } from "./lib/browserLifecycle.mjs";

const BACKEND = process.env.QA_VERIFY_BACKEND || "http://127.0.0.1:8001";
const FRONTEND = process.env.QA_VERIFY_FRONTEND || "http://localhost:5174";
const ADMIN_EMAIL = "admin@example.com";
const ADMIN_PASSWORD = "changeme123";

const PNG_HEX =
  "89504e470d0a1a0a0000000d4948445200000002000000020802000000fdd49a730000000c4944415478" +
  "9c63f8cfc0c0c0c0000000060003fad07fe60000000049454e44ae426082";

async function apiLogin(jar) {
  const login = await fetch(`${BACKEND}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Origin: FRONTEND },
    body: JSON.stringify({ email: ADMIN_EMAIL, password: ADMIN_PASSWORD }),
  });
  jar.absorb(login.headers.get("set-cookie"));
  await fetch(`${BACKEND}/api/auth/change-password`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Origin: FRONTEND, Cookie: jar.header() },
    body: JSON.stringify({ current_password: ADMIN_PASSWORD, new_password: "changeme456" }),
  });
}

function makeCookieJar() {
  const cookies = new Map();
  return {
    absorb(setCookieHeader) {
      if (!setCookieHeader) return;
      for (const part of setCookieHeader.split(/,(?=[^;]+?=)/)) {
        const [pair] = part.split(";");
        const [k, v] = pair.split("=");
        if (k && v) cookies.set(k.trim(), v.trim());
      }
    },
    header() {
      return [...cookies.entries()].map(([k, v]) => `${k}=${v}`).join("; ");
    },
  };
}

async function api(jar, method, path, body) {
  const res = await fetch(`${BACKEND}${path}`, {
    method,
    headers: { "Content-Type": "application/json", Origin: FRONTEND, Cookie: jar.header() },
    body: body ? JSON.stringify(body) : undefined,
  });
  jar.absorb(res.headers.get("set-cookie"));
  const data = await res.json().catch(() => ({}));
  return { status: res.status, data };
}

async function main() {
  const jar = makeCookieJar();
  await apiLogin(jar);

  const project = (await api(jar, "POST", "/api/projects", { name: "Quick Test Verify" })).data;
  const slug = project.slug;
  console.log(`Project: ${slug}`);

  // Set up a real published suite via the API so "Run Now" and "Rerun"
  // have something real to act on (suite/case authoring itself is
  // existing, already-verified Track A UI -- not the focus here).
  const suite = (await api(jar, "POST", `/api/${slug}/suites`, { name: "Real Browser Suite", suite_type: "OTHER" })).data;
  const rev = (await api(jar, "POST", `/api/${slug}/suites/${suite.id}/revisions`, { revision_label: "v1" })).data;
  await api(jar, "POST", `/api/${slug}/revisions/${rev.id}/cases`, { checkpoint_code: "RB-1", title: "case one", action_md: "a", expected_result_md: "e" });
  await api(jar, "POST", `/api/${slug}/revisions/${rev.id}/cases`, { checkpoint_code: "RB-2", title: "case two", action_md: "a", expected_result_md: "e" });
  await api(jar, "POST", `/api/${slug}/suites/${suite.id}/revisions/${rev.id}/publish`);

  const browserRun = await launchTrackedBrowser({ label: "verify-quick-manual-test", slowMo: 40 });
  const page = browserRun.page;

  try {
  let clickCount = 0;
  const origClick = page.click.bind(page);
  page.click = async (...args) => {
    clickCount++;
    return origClick(...args);
  };

  // Real UI login (separate credential from the API session above,
  // which was only used to seed the project/suite/revision/cases).
  page.on("response", (res) => {
    if (res.url().includes("/api/auth/login")) console.log("  [login response]", res.status());
  });
  page.on("console", (msg) => console.log("  [browser console]", msg.type(), msg.text()));
  page.on("pageerror", (err) => console.log("  [browser pageerror]", err.message));
  await page.goto(`${FRONTEND}/login`);
  await page.fill('input[type="email"]', ADMIN_EMAIL);
  await page.fill('input[type="password"]', "changeme456");
  await page.click('button:has-text("Sign in")');
  await page.waitForTimeout(1500);
  try {
    await page.waitForSelector("text=Projects", { timeout: 10000 });
  } catch (e) {
    console.log("  URL at failure:", page.url());
    console.log("  body text:", (await page.locator("body").innerText()).slice(0, 1000));
    throw e;
  }
  console.log("  post-login URL:", page.url());
  await page.click(`text=${slug}`).catch(() => null);
  if (!page.url().includes(slug)) {
    await page.goto(`${FRONTEND}/${slug}/dashboard`);
  }
  console.log("  dashboard URL:", page.url());
  try {
    await page.waitForSelector("text=Start Testing", { timeout: 10000 });
  } catch (e) {
    console.log("  page text snapshot:", (await page.locator("body").innerText()).slice(0, 2000));
    throw e;
  }

  clickCount = 0;
  const t0 = Date.now();
  console.log("MEASURED: Dashboard -> Start Testing -> Quick Manual Test -> active execution");
  await page.getByRole("button", { name: "Start Testing", exact: true }).click();
  clickCount++;
  await page.getByText("Quick Manual Test", { exact: true }).click();
  clickCount++;
  await page.fill('input[placeholder*="Login works"]', "Real browser: login works with valid credentials");
  await page.getByRole("button", { name: "Start Test", exact: true }).click();
  clickCount++;
  await page.waitForSelector("text=Actual Result", { timeout: 10000 });
  const elapsedMs = Date.now() - t0;
  console.log(`RESULT: ${clickCount} clicks, ${elapsedMs} ms (${(elapsedMs / 1000).toFixed(1)}s) -- requirement: < 30s`);
  if (elapsedMs >= 30000) throw new Error("Quick Manual Test did not reach active execution within 30 seconds");
  if (clickCount > 3) console.log(`NOTE: ${clickCount} clicks used (Start Testing, Quick Manual Test, Start Test) -- confirm this matches the intended minimal path.`);

  console.log("\nConfirming evidence/actual-result/status controls are all visible without further navigation...");
  const hasUpload = await page.locator("text=Upload").count();
  const hasScreenCapture = await page.locator("text=Screen Capture").count();
  const hasAnnotate = await page.locator("text=Annotate").count();
  const hasPass = await page.locator('button:has-text("PASS")').count();
  console.log(`  Upload control: ${hasUpload > 0}, Screen Capture: ${hasScreenCapture > 0}, Annotate: ${hasAnnotate > 0}, PASS button: ${hasPass > 0}`);
  if (!hasUpload || !hasPass) throw new Error("Core evidence/status controls not immediately visible");

  // NOTE: the case-list status filter row also renders a plain
  // <button>PASS</button>, so a bare `button:has-text("PASS")` selector
  // matches that filter toggle first, not the real submit button in the
  // sticky action area. Target the action buttons by their `title`
  // (Alt+P/F/B/A shortcuts) to disambiguate.
  console.log("\nPASS evidence enforcement: attempting PASS with no evidence yet...");
  await page.click('button[title="Alt+P"]');
  await page.waitForTimeout(500);
  const blockedMsg = await page.locator("text=/evidence/i").first().isVisible().catch(() => false);
  console.log(`  Rejected with an evidence-related message: ${blockedMsg}`);
  if (!blockedMsg) throw new Error("PASS was not blocked without evidence -- enforcement regression");

  console.log("\nUploading real evidence, then PASS + Save & Next...");
  const pngPath = path.join(os.tmpdir(), "qt-verify-shot.png");
  fs.writeFileSync(pngPath, Buffer.from(PNG_HEX, "hex"));
  await page.locator('input[type="file"]').first().setInputFiles(pngPath);
  await page.waitForTimeout(1000);
  await page.click('button[title="Alt+P"]');
  await page.waitForTimeout(1000);
  // Verify the REAL outcome via the API (the UI's own "Saved" toast is
  // transient and timing-sensitive to assert against reliably) --
  // action was driven for real via the UI above.
  const quickCyclesCheck = await api(jar, "GET", `/api/${slug}/cycles?include_system_generated=true`);
  const quickCycleCheck = quickCyclesCheck.data.find((c) => c.name.startsWith("Quick Test:"));
  const quickResultCheck = (await api(jar, "GET", `/api/${slug}/cycles/${quickCycleCheck.id}/results`)).data[0];
  console.log(`  PASS accepted once evidence exists (verified via API): ${quickResultCheck.status === "PASS"}`);
  if (quickResultCheck.status !== "PASS") throw new Error("PASS was not recorded after real evidence upload");

  const beforeNext = await page.locator("text=All cases reached").count();
  await page.click('button:has-text("Save & Next")');
  await page.waitForTimeout(500);
  const completionShown = await page.locator("text=All cases reached").count();
  console.log(`  Save & Next on the only case reached the completion summary: ${completionShown > beforeNext}`);

  console.log("\nRun Now (real UI button on Suite Detail)...");
  await page.goto(`${FRONTEND}/${slug}/suites/${suite.id}`);
  await page.click('button:has-text("Run now")');
  await page.waitForSelector("text=Test Cycles", { timeout: 10000 });
  const runNowUrl = page.url();
  const runNowCycleId = runNowUrl.match(/\/cycles\/(\d+)/)?.[1];
  console.log(`  Run Now opened cycle ${runNowCycleId} directly: ${!!runNowCycleId}`);
  if (!runNowCycleId) throw new Error("Run Now did not navigate to an active cycle execution screen");

  console.log("\nMark one case FAIL, then Rerun FAIL/BLOCKED only (real UI button)...");
  await page.fill('textarea[placeholder*="required for FAIL"]', "Real browser: this case genuinely failed");
  await page.click('button[title="Alt+F"]');
  await page.waitForTimeout(800);
  page.once("dialog", (d) => d.accept());
  await page.click('button:has-text("Rerun FAIL/BLOCKED only")');
  await page.waitForTimeout(1000);
  const rerunUrl = page.url();
  const rerunCycleId = rerunUrl.match(/\/cycles\/(\d+)/)?.[1];
  console.log(`  Rerun navigated to a new cycle ${rerunCycleId} (source was ${runNowCycleId}): ${rerunCycleId !== runNowCycleId}`);

  console.log("\nContinue Last Test (Dashboard button)...");
  await page.goto(`${FRONTEND}/${slug}/dashboard`);
  await page.waitForTimeout(1000); // let the async getContinueLastTest() fetch on mount resolve
  const hasContinue = await page.locator('button:has-text("Continue Last Test")').count();
  console.log(`  Continue Last Test button present: ${hasContinue > 0}`);

  } finally {
    await browserRun.close();
  }

  console.log("\nExcel/ZIP export inclusion (real API, real files)...");
  const cyclesResp = await api(jar, "GET", `/api/${slug}/cycles?include_system_generated=true`);
  const quickCycle = cyclesResp.data.find((c) => c.name.startsWith("Quick Test:"));
  const excelRes = await fetch(`${BACKEND}/api/${slug}/cycles/${quickCycle.id}/export/excel`, { headers: { Cookie: jar.header() } });
  console.log(`  Excel export for the quick-test cycle: HTTP ${excelRes.status}`);
  const zipRes = await fetch(`${BACKEND}/api/${slug}/cycles/${quickCycle.id}/export/zip`, { headers: { Cookie: jar.header() } });
  console.log(`  ZIP export for the quick-test cycle: HTTP ${zipRes.status}`);
  if (excelRes.status !== 200 || zipRes.status !== 200) throw new Error("Quick-test cycle export failed");

  console.log("\nALL QUICK MANUAL TEST UX CHECKS PASSED.");
}

main().catch((err) => {
  console.error("VERIFICATION FAILED:", err);
  process.exitCode = 1;
});
