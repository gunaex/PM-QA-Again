// Real-Chrome verification for the QA-Again Recorder extension
// (ADR-HYB-002). Loads the ACTUAL unpacked extension into a real,
// headed Chromium instance via Playwright's persistent-context
// extension-loading support -- not a simulation of the extension's
// behavior, the real manifest.json/background.js/content.js/popup.js
// files in extension/ are what gets loaded and exercised.
//
// Drives background.js's real message handlers directly via
// serviceWorker.evaluate() (Playwright's documented way to reach into a
// real, running MV3 service worker) rather than pixel-driving the
// popup overlay UI -- MV3 toolbar popups are a known hard case for
// browser automation (no supported way to trigger the real
// user-gesture toolbar click + overlay popup from outside the browser
// chrome itself). This still exercises the real background.js/
// content.js code running in a real browser against the real backend
// and a real target page -- popup.js itself is a thin ~15-line wrapper
// around the same chrome.runtime.sendMessage calls this script issues
// directly.
//
// Usage: node verify-extension.mjs
// Requires: real backend on 127.0.0.1:8000, real frontend on
// localhost:5173, a project/workflow/session already created (this
// script creates them itself via the real HTTP API).

import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { launchTrackedBrowser } from "./lib/browserLifecycle.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REAL_EXTENSION_PATH = path.resolve(__dirname, "..", "..", "extension");
const BACKEND = process.env.QA_VERIFY_BACKEND || "http://127.0.0.1:8000";
const FRONTEND = process.env.QA_VERIFY_FRONTEND || "http://localhost:5173";
const ADMIN_EMAIL = process.env.QA_VERIFY_ADMIN_EMAIL || "admin@example.com";
const ADMIN_PASSWORD = process.env.QA_VERIFY_ADMIN_PASSWORD || "changeme123";

async function api(cookieJar, method, urlPath, body) {
  const res = await fetch(`${BACKEND}${urlPath}`, {
    method,
    headers: { "Content-Type": "application/json", Origin: FRONTEND, Cookie: cookieJar.header() },
    body: body ? JSON.stringify(body) : undefined,
  });
  const setCookie = res.headers.get("set-cookie");
  if (setCookie) cookieJar.absorb(setCookie);
  const data = await res.json().catch(() => ({}));
  return { status: res.status, data };
}

function makeCookieJar() {
  const cookies = new Map();
  return {
    absorb(setCookieHeader) {
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

async function main() {
  const jar = makeCookieJar();

  const login = await api(jar, "POST", "/api/auth/login", { email: ADMIN_EMAIL, password: ADMIN_PASSWORD });
  if (login.status !== 200) throw new Error(`login failed: ${JSON.stringify(login.data)}`);
  await api(jar, "POST", "/api/auth/change-password", { current_password: ADMIN_PASSWORD, new_password: "changeme456" });

  const project = (await api(jar, "POST", "/api/projects", { name: "Extension Verify" })).data;
  const slug = project.slug;
  console.log(`Project: ${slug}`);

  const workflow = (await api(jar, "POST", `/api/${slug}/workflows`, { name: "Extension Verify Workflow" })).data;
  const session = (
    await api(jar, "POST", `/api/${slug}/recording-sessions`, { workflow_id: workflow.id, target_url: `${FRONTEND}/login` })
  ).data;
  console.log(`Recording session: ${session.id} (status ${session.status})`);

  const auth = (await api(jar, "POST", `/api/${slug}/recording-sessions/${session.id}/authorize-extension`)).data;
  console.log(`Extension authorization minted, expires ${auth.expires_at}`);

  // ---- Real, documented Chrome platform limitation ----
  // chrome.permissions.request() (the real, narrow, per-origin grant
  // popup.js's connectBtn handler calls -- confirmed reachable via a
  // genuine Playwright-dispatched click, which IS accepted as a
  // trusted user gesture) opens a native Chrome permission bubble that
  // only a human can dismiss -- there is no supported browser-
  // automation API to click Chrome's own native UI chrome (as opposed
  // to page content). This is the exact same category of human-only
  // gate this project already accepts for the Screen Capture API and
  // clipboard-paste acceptance checks (see docs/RELEASE_CLOSURE.md).
  //
  // For automated, unattended verification of everything DOWNSTREAM of
  // that one human click (real DOM capture, redaction, undo, stop-time
  // revocation, save-as-draft, publish), this script loads a
  // TEST-ONLY copy of the real extension/ folder with the one backend
  // origin pre-declared as a static host_permission (skipping only the
  // interactive consent dialog itself -- every other file is byte-
  // identical to the real, shipped extension). The genuinely shipped
  // extension/manifest.json keeps host_permissions empty; nothing here
  // changes what end users receive. Manual verification of the actual
  // interactive permission prompt is documented in extension/README.md
  // and was exercised once by hand this session (see the commit
  // message / HYB session notes for the manual confirmation).
  const testExtensionPath = fs.mkdtempSync(path.join(os.tmpdir(), "qa-ext-verify-"));
  for (const file of fs.readdirSync(REAL_EXTENSION_PATH)) {
    if (file === "README.md") continue;
    fs.copyFileSync(path.join(REAL_EXTENSION_PATH, file), path.join(testExtensionPath, file));
  }
  const manifest = JSON.parse(fs.readFileSync(path.join(testExtensionPath, "manifest.json"), "utf-8"));
  // The backend origin is the one real end users grant (their target
  // origin is whatever site they're recording, always visible to
  // chrome.tabs since that's the activeTab they clicked from). The
  // frontend origin is only needed here because this automated harness
  // must locate the target tab by URL via chrome.tabs.query -- a real
  // user never needs this since their tab is already "active" when
  // they click the toolbar icon (activeTab covers it automatically).
  manifest.host_permissions = [`${BACKEND}/*`, `${FRONTEND}/*`];
  fs.writeFileSync(path.join(testExtensionPath, "manifest.json"), JSON.stringify(manifest, null, 2));
  console.log(`Test-only extension copy (real files, pre-granted host_permission for automation): ${testExtensionPath}`);

  let browserRun;
  try {
  console.log("Launching REAL headed Chromium with the extension loaded...");
  browserRun = await launchTrackedBrowser({
    label: "verify-extension",
    args: [`--disable-extensions-except=${testExtensionPath}`, `--load-extension=${testExtensionPath}`],
  });
  const context = browserRun.context;

  let serviceWorker = context.serviceWorkers()[0];
  const deadline = Date.now() + 20000;
  while (!serviceWorker && Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, 250));
    serviceWorker = context.serviceWorkers()[0];
  }
  if (!serviceWorker) {
    throw new Error("Extension service worker never appeared within 20s -- extension failed to load or register.");
  }
  console.log(`Extension service worker: ${serviceWorker.url()}`);
  serviceWorker.on("console", (msg) => console.log("  [sw console]", msg.type(), msg.text()));

  // The target tab -- a normal browsing tab, exactly what a real tester
  // would have open before clicking the extension icon.
  const targetPage = context.pages()[0] || (await context.newPage());
  await targetPage.goto(`${FRONTEND}/login`);
  await targetPage.waitForSelector("text=QA-Again");
  console.log("Target tab loaded: /login");

  // ---- Connect (background.js's real QA_EXT_CONNECT handler, driven
  // via the extension's own real chrome.tabs.query -- host permission
  // for the target's origin is pre-granted in this test-only copy, see
  // above, so the only thing skipped is the interactive prompt itself,
  // not any application logic). ----
  const tabs = await serviceWorker.evaluate(() => chrome.tabs.query({}));
  const targetTab = tabs.find((t) => t.url && t.url.includes("/login"));
  if (!targetTab) throw new Error(`Could not find the target tab. Tabs seen: ${JSON.stringify(tabs)}`);

  // NOTE: chrome.runtime.sendMessage() sent FROM the service worker's
  // own context is never delivered back to that same context's own
  // onMessage listener (Chrome excludes the sender from its own
  // broadcast, precisely to avoid trivial self-messaging loops) -- a
  // real popup/content-script is a genuinely separate context, so this
  // limitation never affects real usage. For this harness, background.js
  // exposes its message logic as a plain top-level async function
  // (handleMessage) so it can be invoked directly -- the exact same code
  // real messages route to, just called without the (self-messaging-
  // incapable) chrome.runtime bus in the middle.
  const callHandler = (serviceWorkerRef, message) =>
    serviceWorkerRef.evaluate(
      (msg) => new Promise((resolve) => handleMessage(msg, resolve)),
      message,
    );

  const connectResp = await callHandler(serviceWorker, {
    type: "QA_EXT_CONNECT",
    backendUrl: BACKEND,
    projectSlug: slug,
    sessionId: session.id,
    extensionToken: auth.token,
    tabId: targetTab.id,
  });
  console.log("QA_EXT_CONNECT response:", connectResp);
  if (!connectResp || !connectResp.ok) throw new Error(`extension-connect failed: ${JSON.stringify(connectResp)}`);

  await targetPage.waitForTimeout(500); // let the content script attach

  // ---- Real DOM interactions on the target tab (real user input) ----
  console.log("Performing real interactions on the target tab (email, password, sign-in)...");
  await targetPage.fill('input[type="email"]', "tester@example.com");
  await targetPage.fill('input[type="password"]', "hunter2-should-never-appear-in-backend");
  await targetPage.click('button:has-text("Sign in")');
  await targetPage.waitForTimeout(500);

  // ---- Verify against the REAL backend that steps were captured ----
  const detail1 = (await api(jar, "GET", `/api/${slug}/recording-sessions/${session.id}`)).data;
  console.log(`Captured steps so far: ${detail1.recorded_steps.map((s) => s.step_type).join(", ")}`);
  const passwordStep = detail1.recorded_steps.find((s) => s.step_type === "FILL" && (s.locator_value || "").includes("Password"));
  if (!passwordStep) throw new Error(`Password FILL step was not captured. Steps: ${JSON.stringify(detail1.recorded_steps)}`);
  if (passwordStep.input_value) throw new Error(`SECURITY FAILURE: password value leaked to backend: ${passwordStep.input_value}`);
  if (!passwordStep.is_sensitive) throw new Error("Password step was not flagged is_sensitive");
  console.log("PASS: password redaction confirmed -- is_sensitive=true, input_value=null, real value never reached the backend.");

  // ---- Pause / Resume ----
  const pauseResp = await callHandler(serviceWorker, { type: "QA_EXT_PAUSE" });
  console.log("Pause:", pauseResp.ok, pauseResp.session?.status);
  const resumeResp = await callHandler(serviceWorker, { type: "QA_EXT_RESUME" });
  console.log("Resume:", resumeResp.ok, resumeResp.session?.status);

  // ---- A dropdown (SELECT) and a checkbox (CHECK/UNCHECK), on the
  // Projects page, which the login redirect lands on ----
  await targetPage.waitForSelector("text=Projects", { timeout: 10000 }).catch(() => {});
  const hasArchivedCheckbox = await targetPage.locator('text=Show archived').count();
  if (hasArchivedCheckbox > 0) {
    await targetPage.check('input[type="checkbox"]');
    await targetPage.uncheck('input[type="checkbox"]');
    console.log("Exercised a real checkbox CHECK/UNCHECK on the Projects page.");
  }

  // ---- Undo last step ----
  const beforeUndo = (await api(jar, "GET", `/api/${slug}/recording-sessions/${session.id}`)).data;
  const countBefore = beforeUndo.recorded_steps.length;
  const undoResp = await callHandler(serviceWorker, { type: "QA_EXT_UNDO" });
  console.log("Undo:", undoResp.ok, "remaining steps:", undoResp.session?.recorded_steps?.length);
  if (undoResp.session.recorded_steps.length !== countBefore - 1) throw new Error("Undo did not remove exactly one step");
  console.log("PASS: undo-last-step removed exactly one step.");

  // ---- Stop ----
  const stopResp = await callHandler(serviceWorker, { type: "QA_EXT_STOP" });
  console.log("Stop:", stopResp.ok, stopResp.session?.status);
  if (stopResp.session?.status !== "STOPPED") throw new Error("Session did not reach STOPPED");

  // ---- Confirm the extension token is now revoked (real backend check) ----
  const reuseAttempt = await fetch(`${BACKEND}/api/${slug}/recording-sessions/${session.id}/heartbeat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ extension_token: auth.token }),
  });
  // heartbeat on a terminal-status session is a no-op 200 regardless of
  // token validity (matches existing precedent) -- the real revocation
  // check is a mutating call:
  const reuseStep = await fetch(`${BACKEND}/api/${slug}/recording-sessions/${session.id}/steps`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ step_type: "SCREENSHOT", extension_token: auth.token }),
  });
  console.log(`Revoked-token reuse attempt against /steps: HTTP ${reuseStep.status} (expect 401)`);
  if (reuseStep.status !== 401) throw new Error("Revoked extension token was NOT rejected -- security regression");
  console.log("PASS: extension authorization was revoked on stop.");

  // ---- Human review: assign a ${SECRET_NAME} placeholder to the
  // sensitive step before saving -- the recorder deliberately never
  // invents one; a human must (same rule as the Playwright-mode
  // recorder and hand-authored workflow steps alike). ----
  const preSaveDetail = (await api(jar, "GET", `/api/${slug}/recording-sessions/${session.id}`)).data;
  const stillSensitive = preSaveDetail.recorded_steps.find((s) => s.is_sensitive);
  if (stillSensitive) {
    const named = await api(
      jar, "PUT", `/api/${slug}/recording-sessions/${session.id}/steps/${stillSensitive.id}`,
      { input_value: "${SECRET_LOGIN_PASSWORD}" },
    );
    if (named.status !== 200) throw new Error(`Could not assign placeholder: ${JSON.stringify(named.data)}`);
    console.log("PASS: assigned ${SECRET_LOGIN_PASSWORD} placeholder to the sensitive step during human review.");
  }

  // ---- Human review + save-as-draft + publish (unchanged existing code path) ----
  const saved = await api(jar, "POST", `/api/${slug}/recording-sessions/${session.id}/save-as-draft`, { revision_label: "ext-verify-v1" });
  console.log("Save as draft:", saved.status, saved.data.status);
  if (saved.status !== 200) throw new Error(`save-as-draft failed: ${JSON.stringify(saved.data)}`);
  const published = await api(jar, "POST", `/api/${slug}/workflows/${workflow.id}/revisions/${saved.data.id}/publish`);
  console.log("Publish:", published.status, published.data.status);
  if (published.status !== 200) throw new Error("publish failed");

  console.log("\nALL EXTENSION VERIFICATION CHECKS PASSED (real Chrome, real extension, real backend).");
  console.log(`Published workflow revision id: ${saved.data.id} -- ready for replay via the real QA Runner.`);
  } finally {
    if (browserRun) await browserRun.close();
    fs.rmSync(testExtensionPath, { recursive: true, force: true });
  }
}

main().catch((err) => {
  console.error("EXTENSION VERIFICATION FAILED:", err);
  process.exitCode = 1;
});
