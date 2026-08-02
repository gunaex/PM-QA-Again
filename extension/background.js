// QA-Again Chrome extension recorder -- background service worker.
//
// Holds the short-lived, recording-session-scoped authorization
// (never the tester's own JWT, never a global RunnerToken) ONLY in
// chrome.storage.session -- cleared automatically when the browser
// closes, never chrome.storage.local. Injects the content script into
// the one authorized tab (activeTab + chrome.scripting.executeScript,
// only after an explicit "Start Recording" user gesture in the popup),
// forwards captured events to the QA-Again backend, and reports
// real navigations it observes on that tab via chrome.tabs.onUpdated.

const HEARTBEAT_INTERVAL_MS = 5 * 60 * 1000; // well inside the 30-minute renewal window
let heartbeatTimer = null;

async function getState() {
  const stored = await chrome.storage.session.get(["config"]);
  return stored.config || null;
}

async function setState(config) {
  await chrome.storage.session.set({ config });
}

async function clearState() {
  await chrome.storage.session.remove(["config"]);
  if (heartbeatTimer) {
    clearInterval(heartbeatTimer);
    heartbeatTimer = null;
  }
}

function apiUrl(config, path) {
  return `${config.backendUrl.replace(/\/$/, "")}/api/${config.projectSlug}${path}`;
}

async function postJson(config, path, body) {
  // credentials: "omit" -- this extension authenticates purely via
  // config.extensionToken, never a cookie. Without this, a tester
  // logged into the QA-Again web app in the SAME Chrome profile gets
  // that session cookie auto-attached to these cross-origin requests
  // (host_permissions grant normal cookie access), which then trips
  // the backend's CSRF-origin guard and 403s every extension call.
  const res = await fetch(apiUrl(config, path), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    credentials: "omit",
  });
  const data = await res.json().catch(() => ({}));
  return { ok: res.ok, status: res.status, data };
}

async function startHeartbeat() {
  if (heartbeatTimer) clearInterval(heartbeatTimer);
  heartbeatTimer = setInterval(async () => {
    const config = await getState();
    if (!config || !config.recording) return;
    await postJson(config, `/recording-sessions/${config.sessionId}/heartbeat`, { extension_token: config.extensionToken });
  }, HEARTBEAT_INTERVAL_MS);
}

async function injectContentScript(tabId) {
  await chrome.scripting.executeScript({ target: { tabId }, files: ["content.js"] });
}

async function setContentScriptPaused(tabId, paused) {
  try {
    await chrome.tabs.sendMessage(tabId, { type: "QA_EXT_SET_PAUSED", paused });
  } catch {
    // Tab may have navigated and the content script hasn't re-attached
    // yet -- the next injection will start in the correct paused state.
  }
}

// ---------- message handling from the popup ----------

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  (async () => {
    try {
      await handleMessage(message, sendResponse);
    } catch (err) {
      console.error("QA-Again Recorder: unhandled error handling", message.type, err);
      sendResponse({ ok: false, error: String(err && err.message ? err.message : err) });
    }
  })();
  return true; // keep the message channel open for the async response
});

// Exposed on `self` (the service worker global) because this file is
// loaded as an ES module ("type": "module" in manifest.json) -- a
// module's top-level function declarations are scoped to the module,
// not attached to the global object the way a classic script's would
// be, so an external CDP-level evaluate (used only by this project's
// own automated verification harness, never by real usage) needs an
// explicit reference to reach it.
self.handleMessage = handleMessage;

async function handleMessage(message, sendResponse) {
  {
    if (message.type === "QA_EXT_CONNECT") {
      const { backendUrl, projectSlug, sessionId, extensionToken, tabId } = message;
      const config = { backendUrl, projectSlug, sessionId, extensionToken, tabId, recording: false };
      const connect = await postJson(config, `/recording-sessions/${sessionId}/extension-connect`, { extension_token: extensionToken });
      if (!connect.ok) {
        sendResponse({ ok: false, error: connect.data.detail || "Could not connect" });
        return;
      }
      config.recording = true;
      await setState(config);
      await injectContentScript(tabId);
      await startHeartbeat();
      chrome.tabs.onUpdated.addListener(onTabUpdated);
      sendResponse({ ok: true, session: connect.data });
      return;
    }

    if (message.type === "QA_EXT_PAUSE" || message.type === "QA_EXT_RESUME") {
      const config = await getState();
      if (!config) {
        sendResponse({ ok: false, error: "Not connected" });
        return;
      }
      const action = message.type === "QA_EXT_PAUSE" ? "pause" : "resume";
      const res = await postJson(config, `/recording-sessions/${config.sessionId}/${action}?extension_token=${encodeURIComponent(config.extensionToken)}`, {});
      if (res.ok) {
        await setContentScriptPaused(config.tabId, action === "pause");
      }
      sendResponse({ ok: res.ok, session: res.data, error: res.data.detail });
      return;
    }

    if (message.type === "QA_EXT_UNDO") {
      const config = await getState();
      if (!config) {
        sendResponse({ ok: false, error: "Not connected" });
        return;
      }
      const res = await postJson(config, `/recording-sessions/${config.sessionId}/undo-last-step?extension_token=${encodeURIComponent(config.extensionToken)}`, {});
      sendResponse({ ok: res.ok, session: res.data, error: res.data.detail });
      return;
    }

    if (message.type === "QA_EXT_STOP") {
      const config = await getState();
      if (!config) {
        sendResponse({ ok: false, error: "Not connected" });
        return;
      }
      const res = await postJson(config, `/recording-sessions/${config.sessionId}/stop?extension_token=${encodeURIComponent(config.extensionToken)}`, {});
      chrome.tabs.onUpdated.removeListener(onTabUpdated);
      await clearState();
      sendResponse({ ok: res.ok, session: res.data, error: res.data.detail });
      return;
    }

    if (message.type === "QA_EXT_STATUS") {
      const config = await getState();
      sendResponse({ ok: true, config });
      return;
    }

    if (message.type === "QA_EXT_RECORDED_EVENT") {
      const config = await getState();
      if (!config || !config.recording) {
        sendResponse({ ok: false });
        return;
      }
      const p = message.payload;
      const idempotencyKey = crypto.randomUUID();
      const res = await postJson(config, `/recording-sessions/${config.sessionId}/steps`, {
        step_type: p.stepType,
        description: p.description,
        locator_strategy: p.locatorStrategy,
        locator_value: p.locatorValue,
        locator_fallbacks_json: p.locatorFallbacks ? JSON.stringify(p.locatorFallbacks) : undefined,
        locator_warnings_json: p.locatorWarnings && p.locatorWarnings.length ? JSON.stringify(p.locatorWarnings) : undefined,
        target_summary: p.targetSummary,
        page_context: p.pageContext,
        diagnostic_x: p.diagnosticX,
        diagnostic_y: p.diagnosticY,
        input_value: p.inputValue,
        is_sensitive: !!p.isSensitive,
        checkpoint_instructions: p.checkpointInstructions,
        needs_review: !!p.needsReview,
        review_note: p.reviewNote,
        extension_token: config.extensionToken,
        idempotency_key: idempotencyKey,
      });
      sendResponse({ ok: res.ok });
      return;
    }
  }
}

// ---------- real navigation reporting (mirrors the Playwright mode's
// own framenavigated-based NAVIGATE capture) ----------

let lastReportedUrl = null;

async function onTabUpdated(tabId, changeInfo) {
  const config = await getState();
  if (!config || !config.recording || tabId !== config.tabId) return;
  if (changeInfo.status !== "complete" || !changeInfo.url) return;
  if (changeInfo.url === lastReportedUrl) return;
  lastReportedUrl = changeInfo.url;

  const idempotencyKey = crypto.randomUUID();
  await postJson(config, `/recording-sessions/${config.sessionId}/steps`, {
    step_type: "NAVIGATE",
    input_value: changeInfo.url,
    page_context: new URL(changeInfo.url).pathname,
    extension_token: config.extensionToken,
    idempotency_key: idempotencyKey,
  });
  // Full-page navigations tear down any previously injected content
  // script -- re-inject so recording continues on the new page.
  await injectContentScript(tabId);
}
