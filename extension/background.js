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

async function captureSelectedTab(config) {
  const tab = await chrome.tabs.get(config.tabId);
  if (!tab.active) throw new Error("Open the test tab before capturing its screenshot.");
  return chrome.tabs.captureVisibleTab(tab.windowId, { format: "png" });
}

function installPageActivityTracker() {
  if (window.__qaAgainActivityTracker) return;
  const tracker = { pending: 0, lastActivity: Date.now() };
  window.__qaAgainActivityTracker = tracker;
  const touch = () => { tracker.lastActivity = Date.now(); };

  const originalFetch = window.fetch;
  window.fetch = function (...args) {
    tracker.pending += 1;
    touch();
    return originalFetch.apply(this, args).finally(() => {
      tracker.pending = Math.max(0, tracker.pending - 1);
      touch();
    });
  };

  const originalSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.send = function (...args) {
    tracker.pending += 1;
    touch();
    this.addEventListener("loadend", () => {
      tracker.pending = Math.max(0, tracker.pending - 1);
      touch();
    }, { once: true });
    return originalSend.apply(this, args);
  };

  new MutationObserver(touch).observe(document.documentElement, {
    childList: true,
    subtree: true,
    attributes: true,
    characterData: true,
  });
}

async function waitForPageActivityToSettle(quietMs, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const tracker = window.__qaAgainActivityTracker;
    if (
      document.readyState === "complete"
      && tracker
      && tracker.pending === 0
      && Date.now() - tracker.lastActivity >= quietMs
    ) return { ok: true };
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  const pending = window.__qaAgainActivityTracker?.pending || 0;
  return { ok: false, pending };
}

async function waitForSelectedTabStable(config, timeoutMs = 30000) {
  await chrome.scripting.executeScript({
    target: { tabId: config.tabId },
    world: "MAIN",
    func: installPageActivityTracker,
  });
  const result = await chrome.scripting.executeScript({
    target: { tabId: config.tabId },
    world: "MAIN",
    func: waitForPageActivityToSettle,
    args: [600, timeoutMs],
  });
  const state = result[0]?.result;
  if (!state?.ok) {
    throw new Error(state?.pending
      ? `Page did not finish ${state.pending} network request(s) before the timeout`
      : "Page did not finish rendering before the timeout");
  }
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

async function injectPlaybackScript(tabId) {
  await chrome.scripting.executeScript({ target: { tabId }, files: ["playback.js"] });
}

async function sendPlaybackUi(config, message) {
  try {
    await chrome.tabs.sendMessage(config.tabId, {
      type: "QA_EXT_PLAYBACK_UI",
      workflowName: config.workflowName,
      ...message,
    });
  } catch {
    // Navigation temporarily removes the overlay. The playback loop
    // re-injects it after the new document reaches complete.
  }
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
      await handleMessage(message, sendResponse, sender);
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

async function handleMessage(message, sendResponse, sender = null) {
  {
    if (message.type === "QA_EXT_CONNECT") {
      const { backendUrl, projectSlug, sessionId, extensionToken, tabId, targetUrl } = message;
      const config = { mode: "recording", backendUrl, projectSlug, sessionId, extensionToken, tabId, recording: false };
      const connect = await postJson(config, `/recording-sessions/${sessionId}/extension-connect`, {
        extension_token: extensionToken,
        target_url: targetUrl,
      });
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

    if (message.type === "QA_EXT_ATTACH_PLAYBACK") {
      const { backendUrl, projectSlug, runId, extensionToken, tabId } = message;
      const current = await getState();
      if (current && current.mode === "playback" && current.state === "RUNNING") {
        sendResponse({ ok: false, error: "A test is already running in this browser window." });
        return;
      }
      const config = { mode: "playback", backendUrl, projectSlug, runId, extensionToken, tabId, state: "ATTACHING" };
      const connect = await postJson(config, `/workflow-runs/${runId}/browser-connect`, { extension_token: extensionToken });
      if (!connect.ok) {
        sendResponse({ ok: false, error: connect.data.detail || "Could not attach this test" });
        return;
      }
      config.state = "READY";
      config.steps = connect.data.steps || [];
      config.workflowName = connect.data.run?.workflow_name || `Test run ${runId}`;
      await setState(config);
      await injectPlaybackScript(tabId);
      await sendPlaybackUi(config, {
        state: "READY",
        message: "This tab is selected. Move the controller, then press Start.",
        completed: 0,
        total: config.steps.length,
      });
      sendResponse({ ok: true, run: connect.data.run, stepCount: config.steps.length });
      return;
    }

    if (message.type === "QA_EXT_PLAYBACK_OVERLAY_READY") {
      const config = await getState();
      if (!config || config.mode !== "playback") {
        sendResponse({ ok: false });
        return;
      }
      await sendPlaybackUi(config, {
        state: config.state,
        message: config.state === "READY" ? "This tab is selected. Nothing runs until you press Start." : "Test is running…",
        completed: config.completed || 0,
        total: (config.steps || []).length,
      });
      sendResponse({ ok: true });
      return;
    }

    if (message.type === "QA_EXT_PLAYBACK_START") {
      const config = await getState();
      if (!config || config.mode !== "playback" || config.state !== "READY") {
        sendResponse({ ok: false, error: "This test is not ready. Attach it to the target tab again." });
        return;
      }
      if (sender?.tab?.id && sender.tab.id !== config.tabId) {
        sendResponse({ ok: false, error: "Start must be pressed in the selected target tab." });
        return;
      }
      const result = await runPlayback(config);
      sendResponse(result);
      return;
    }

    if (message.type === "QA_EXT_PLAYBACK_CANCEL") {
      const config = await getState();
      if (!config || config.mode !== "playback") {
        sendResponse({ ok: false, error: "No prepared test is attached." });
        return;
      }
      config.state = "CANCELLED";
      await setState(config);
      await postJson(config, `/workflow-runs/${config.runId}/browser-complete`, {
        extension_token: config.extensionToken,
        status: "CANCELLED",
        result_summary: "Cancelled from the floating browser controller",
      });
      await sendPlaybackUi(config, { state: "CANCELLED", message: "Test cancelled." });
      await clearState();
      sendResponse({ ok: true });
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

// ---------- tester-selected-tab playback ----------

function waitForTabComplete(tabId, timeoutMs = 15000) {
  return new Promise((resolve, reject) => {
    let settled = false;
    const timer = setTimeout(() => finish(new Error("Timed out waiting for navigation")), timeoutMs);
    const listener = (updatedTabId, changeInfo) => {
      if (updatedTabId === tabId && changeInfo.status === "complete") finish();
    };
    function finish(error) {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      chrome.tabs.onUpdated.removeListener(listener);
      error ? reject(error) : resolve();
    }
    chrome.tabs.onUpdated.addListener(listener);
    chrome.tabs.get(tabId).then((tab) => {
      if (tab.status === "complete") finish();
    }).catch((error) => finish(error));
  });
}

async function runDomPlaybackStep(step) {
  const timeoutMs = Math.max(250, Number(step.timeout_ms) || 15000);
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const textOf = (element) => (element?.innerText || element?.textContent || "").replace(/\s+/g, " ").trim();

  function implicitRole(element) {
    const explicit = element.getAttribute("role");
    if (explicit) return explicit;
    const tag = element.tagName.toLowerCase();
    if (tag === "button") return "button";
    if (tag === "a" && element.hasAttribute("href")) return "link";
    if (tag === "select") return "combobox";
    if (tag === "textarea") return "textbox";
    if (tag === "input") {
      const type = (element.type || "text").toLowerCase();
      if (["submit", "button"].includes(type)) return "button";
      if (type === "checkbox") return "checkbox";
      if (type === "radio") return "radio";
      return "textbox";
    }
    return null;
  }

  function labelText(element) {
    if (element.getAttribute("aria-label")) return element.getAttribute("aria-label").trim();
    if (element.id) {
      const label = document.querySelector(`label[for="${CSS.escape(element.id)}"]`);
      if (label) return textOf(label);
    }
    const parent = element.closest("label");
    return parent ? textOf(parent) : "";
  }

  function findNow() {
    const strategy = step.locator_strategy;
    const value = step.locator_value || "";
    if (!strategy) return document.activeElement || document.body;
    if (strategy === "TEST_ID") {
      const escaped = CSS.escape(value);
      return document.querySelector(`[data-testid="${escaped}"],[data-test-id="${escaped}"],[data-qa="${escaped}"]`);
    }
    if (strategy === "CSS") return document.querySelector(value);
    if (strategy === "XPATH") return document.evaluate(value, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
    if (strategy === "PLACEHOLDER") return [...document.querySelectorAll("input,textarea")].find((el) => el.placeholder === value);
    if (strategy === "LABEL") return [...document.querySelectorAll("input,textarea,select,button")].find((el) => labelText(el) === value);
    if (strategy === "TEXT") return [...document.querySelectorAll("button,a,[role],label,span,div")].find((el) => textOf(el) === value) ||
      [...document.querySelectorAll("button,a,[role],label")].find((el) => textOf(el).includes(value));
    if (strategy === "ROLE") {
      const separator = value.indexOf(":");
      const role = separator >= 0 ? value.slice(0, separator) : value;
      const name = separator >= 0 ? value.slice(separator + 1) : "";
      return [...document.querySelectorAll("button,a,input,textarea,select,[role]")].find((el) => {
        const accessibleName = el.getAttribute("aria-label") || labelText(el) || textOf(el) || el.value || "";
        return implicitRole(el) === role && (!name || accessibleName.trim() === name.trim());
      });
    }
    return null;
  }

  async function find() {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      const element = findNow();
      if (element) return element;
      await sleep(120);
    }
    throw new Error(`Element not found: ${step.locator_strategy}=${step.locator_value}`);
  }

  const type = step.step_type;
  if (type === "WAIT") {
    await sleep(Math.min(60000, Math.max(0, Number(step.input_value) || 0)));
    return {};
  }
  if (type === "ASSERT_TEXT") {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      if (textOf(document.body).includes(step.expected_value || "")) return {};
      await sleep(120);
    }
    throw new Error(`Expected page text to include "${step.expected_value || ""}"`);
  }
  if (type === "ASSERT_URL") {
    if (!step.expected_value || location.href.includes(step.expected_value)) return {};
    throw new Error(`Expected URL to include "${step.expected_value}", got "${location.href}"`);
  }
  if (type === "SCREENSHOT") return { skipped: true, outcome: "Visible-tab evidence upload is not enabled in extension playback yet." };
  if (type === "MANUAL_CHECKPOINT") {
    const accepted = window.confirm(step.checkpoint_instructions || "Confirm this manual checkpoint to continue the test.");
    if (!accepted) throw new Error("Manual checkpoint was not accepted");
    return {};
  }

  const element = await find();
  if (type === "CLICK") element.click();
  else if (type === "FILL") {
    let value = step.input_value || "";
    if (step.is_sensitive) {
      value = window.prompt(`Enter the secret value for ${step.description || step.locator_value || "this field"}. It stays in this tab and is never sent to QA-Again.`);
      if (value === null) throw new Error("Sensitive value entry was cancelled");
    }
    element.focus();
    element.value = value;
    element.dispatchEvent(new Event("input", { bubbles: true }));
    element.dispatchEvent(new Event("change", { bubbles: true }));
  } else if (type === "SELECT") {
    const wanted = step.input_value || "";
    const option = [...element.options].find((item) => item.value === wanted || item.text === wanted);
    if (!option) throw new Error(`Select option not found: ${wanted}`);
    element.value = option.value;
    element.dispatchEvent(new Event("change", { bubbles: true }));
  } else if (type === "CHECK" || type === "UNCHECK") {
    element.checked = type === "CHECK";
    element.dispatchEvent(new Event("input", { bubbles: true }));
    element.dispatchEvent(new Event("change", { bubbles: true }));
  } else if (type === "PRESS_KEY") {
    element.focus();
    const key = step.input_value || "Enter";
    element.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true }));
    element.dispatchEvent(new KeyboardEvent("keyup", { key, bubbles: true }));
    if (key === "Enter" && element.form?.requestSubmit) element.form.requestSubmit();
  } else if (type === "WAIT_FOR_ELEMENT") {
    // find() already waited until the element existed.
  } else if (type === "ASSERT_VISIBLE") {
    const rect = element.getBoundingClientRect();
    if (!rect.width || !rect.height || getComputedStyle(element).visibility === "hidden") throw new Error("Expected element to be visible");
  } else {
    throw new Error(`Unsupported browser-extension action: ${type}`);
  }
  return { locatorUsedJson: JSON.stringify({ strategy: step.locator_strategy, value: step.locator_value }) };
}

async function executePlaybackStep(config, step) {
  if (step.step_type === "SCREENSHOT") {
    await waitForSelectedTabStable(config, step.timeout_ms || 30000);
    return { screenshotDataUrl: await captureSelectedTab(config), outcome: "Screenshot captured." };
  }
  if (step.step_type === "NAVIGATE") {
    const tab = await chrome.tabs.get(config.tabId);
    const raw = step.input_value || "";
    const target = /^https?:\/\//.test(raw) ? raw : new URL(raw, tab.url).href;
    await chrome.tabs.update(config.tabId, { url: target });
    await waitForTabComplete(config.tabId, step.timeout_ms || 15000);
    await injectPlaybackScript(config.tabId);
    await sendPlaybackUi(config, {
      state: "RUNNING",
      message: `Running action ${(config.completed || 0) + 1} of ${(config.steps || []).length}`,
      completed: config.completed || 0,
      total: (config.steps || []).length,
    });
    await waitForSelectedTabStable(config, step.timeout_ms || 30000);
    return step.evidence_policy === "REQUIRED"
      ? { screenshotDataUrl: await captureSelectedTab(config), outcome: "Action passed; screenshot captured." }
      : {};
  }
  await chrome.scripting.executeScript({
    target: { tabId: config.tabId },
    world: "MAIN",
    func: installPageActivityTracker,
  });
  const before = await chrome.tabs.get(config.tabId);
  const results = await chrome.scripting.executeScript({
    target: { tabId: config.tabId },
    func: runDomPlaybackStep,
    args: [step],
  });
  // A CLICK/PRESS may begin a full-page navigation just after the DOM
  // function returns. Give Chrome a moment to expose the loading state,
  // then wait and restore the floating controller in the new document.
  if (["CLICK", "PRESS_KEY"].includes(step.step_type)) {
    await new Promise((resolve) => setTimeout(resolve, 250));
    const after = await chrome.tabs.get(config.tabId);
    if (after.status === "loading") await waitForTabComplete(config.tabId, step.timeout_ms || 15000);
    if (after.url !== before.url || after.status === "loading") {
      await injectPlaybackScript(config.tabId);
      await sendPlaybackUi(config, {
        state: "RUNNING",
        message: `Running action ${(config.completed || 0) + 1} of ${(config.steps || []).length}`,
        completed: config.completed || 0,
        total: (config.steps || []).length,
      });
    }
  }
  await waitForSelectedTabStable(config, step.timeout_ms || 30000);
  const result = results[0]?.result || {};
  if (step.evidence_policy === "REQUIRED") {
    result.screenshotDataUrl = await captureSelectedTab(config);
    result.outcome = result.outcome || "Action passed; screenshot captured.";
  }
  return result;
}

function failureCategory(stepType, error) {
  const message = String(error?.message || error);
  if (/not found/i.test(message)) return "LOCATOR_NOT_FOUND";
  if (/timed out|timeout/i.test(message)) return "TIMEOUT";
  if (stepType.startsWith("ASSERT")) return "ASSERTION_FAILED";
  if (stepType === "NAVIGATE") return "NAVIGATION_ERROR";
  return "SYSTEM_ERROR";
}

async function runPlayback(config) {
  const started = await postJson(config, `/workflow-runs/${config.runId}/browser-start`, { extension_token: config.extensionToken });
  if (!started.ok) return { ok: false, error: started.data.detail || "Could not start this test" };
  config.state = "RUNNING";
  config.completed = 0;
  await setState(config);
  await sendPlaybackUi(config, { state: "RUNNING", message: "Test started…", completed: 0, total: config.steps.length });

  let finalStatus = "PASSED";
  let summary = null;
  for (const step of config.steps) {
    const current = await getState();
    if (!current || current.mode !== "playback" || current.state === "CANCELLED") return { ok: true, status: "CANCELLED" };
    const serverState = await postJson(config, `/workflow-runs/${config.runId}/browser-status`, { extension_token: config.extensionToken });
    if (!serverState.ok || serverState.data.cancel_requested) {
      finalStatus = "CANCELLED";
      summary = "Cancelled from QA-Again";
      break;
    }
    const repeatCount = Math.max(1, Number(step.repeat_count) || 1);
    for (let attempt = 1; attempt <= repeatCount; attempt += 1) {
      const actionStartedAt = performance.now();
      await sendPlaybackUi(config, {
        state: "RUNNING",
        message: `Action ${config.completed + 1}/${config.steps.length}: ${step.description || step.step_type}`,
        completed: config.completed,
        total: config.steps.length,
      });
      try {
        const result = await executePlaybackStep(config, step);
        const durationMs = Math.max(0, Math.round(performance.now() - actionStartedAt));
        if (result.screenshotDataUrl) {
          const uploaded = await postJson(config, `/workflow-runs/${config.runId}/browser-screenshot`, {
            extension_token: config.extensionToken,
            workflow_step_id: step.id,
            data_url: result.screenshotDataUrl,
          });
          if (!uploaded.ok) throw new Error(uploaded.data.detail || "Could not save screenshot");
        }
        await postJson(config, `/workflow-runs/${config.runId}/browser-step`, {
          extension_token: config.extensionToken,
          workflow_step_id: step.id,
          attempt_number: attempt,
          status: result.skipped ? "SKIPPED" : "PASSED",
          outcome: result.outcome,
          locator_used_json: result.locatorUsedJson,
          duration_ms: durationMs,
        });
      } catch (error) {
        const durationMs = Math.max(0, Math.round(performance.now() - actionStartedAt));
        const category = failureCategory(step.step_type, error);
        const message = step.is_sensitive ? `${category} (details hidden for sensitive action)` : String(error?.message || error);
        await postJson(config, `/workflow-runs/${config.runId}/browser-step`, {
          extension_token: config.extensionToken,
          workflow_step_id: step.id,
          attempt_number: attempt,
          status: "FAILED",
          failure_category: category,
          machine_message: message,
          duration_ms: durationMs,
        });
        finalStatus = "FAILED";
        summary = message;
        break;
      }
    }
    config.completed += 1;
    await setState(config);
    if (finalStatus === "FAILED") break;
  }

  const completed = await postJson(config, `/workflow-runs/${config.runId}/browser-complete`, {
    extension_token: config.extensionToken,
    status: finalStatus,
    result_summary: summary,
  });
  const finalMessage = finalStatus === "PASSED" ? "Test passed." : finalStatus === "CANCELLED" ? "Test cancelled." : `Test failed: ${summary || "unknown error"}`;
  await sendPlaybackUi(config, { state: finalStatus, message: finalMessage, completed: config.completed, total: config.steps.length });
  await clearState();
  return completed.ok ? { ok: true, status: finalStatus } : { ok: false, error: completed.data.detail || "Could not save the result" };
}
