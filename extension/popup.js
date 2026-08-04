// QA-Again Chrome extension recorder -- popup script.
//
// Runs in an extension page context with direct user-gesture access,
// so this is where the optional host-permission request happens (never
// a broad, permanent host_permission declared in the manifest -- see
// manifest.json's empty host_permissions + optional_host_permissions).

const statusEl = document.getElementById("status");
const connectForm = document.getElementById("connectForm");
const controls = document.getElementById("controls");

function setStatus(text) {
  statusEl.textContent = text;
}

function showConnected() {
  connectForm.classList.add("hidden");
  controls.classList.remove("hidden");
}

function showDisconnected() {
  connectForm.classList.remove("hidden");
  controls.classList.add("hidden");
}

function showPlaybackConnected() {
  connectForm.classList.add("hidden");
  controls.classList.add("hidden");
}

async function refreshStatus() {
  const resp = await chrome.runtime.sendMessage({ type: "QA_EXT_STATUS" });
  if (resp && resp.config && resp.config.recording) {
    showConnected();
    setStatus(`Connected -- session ${resp.config.sessionId} on ${resp.config.backendUrl}`);
  } else if (resp && resp.config && resp.config.mode === "playback") {
    showPlaybackConnected();
    setStatus(`Test run ${resp.config.runId} is ${resp.config.state}. Use the floating controller in the selected tab.`);
  } else {
    showDisconnected();
  }
}

// Decodes the one-paste pairing code (base64 JSON: {backendUrl,
// projectSlug, sessionId, token}) minted by POST .../authorize-extension.
// Returns null (and sets a status message) if the pasted text isn't a
// valid pairing code -- never throws.
function decodePairingCode(raw) {
  try {
    const decoded = JSON.parse(atob(raw));
    const mode = decoded.mode === "playback" ? "playback" : "recording";
    if (!decoded.backendUrl || !decoded.projectSlug || !decoded.token || (mode === "playback" ? !decoded.runId : !decoded.sessionId)) {
      setStatus("Pairing code is missing fields -- copy it again from QA-Again.");
      return null;
    }
    return {
      mode,
      backendUrl: String(decoded.backendUrl),
      projectSlug: String(decoded.projectSlug),
      sessionId: decoded.sessionId ? String(decoded.sessionId) : null,
      runId: decoded.runId ? String(decoded.runId) : null,
      extensionToken: String(decoded.token),
    };
  } catch {
    setStatus("Pairing code is not valid -- copy it again from QA-Again.");
    return null;
  }
}

// Primary path: a single pasted pairing code. Falls back to the four
// manually-entered Advanced fields (unchanged, pre-pairing-code
// behavior) when the pairing code box is left empty.
function resolveConnectionFields() {
  const pairingCodeRaw = document.getElementById("pairingCode").value.trim();
  if (pairingCodeRaw) {
    return decodePairingCode(pairingCodeRaw);
  }

  const backendUrl = document.getElementById("backendUrl").value.trim();
  const projectSlug = document.getElementById("projectSlug").value.trim();
  const sessionId = document.getElementById("sessionId").value.trim();
  const extensionToken = document.getElementById("extensionToken").value.trim();

  if (!backendUrl || !projectSlug || !sessionId || !extensionToken) {
    setStatus("Paste a pairing code, or fill in every Advanced field.");
    return null;
  }
  return { mode: "recording", backendUrl, projectSlug, sessionId, extensionToken };
}

document.getElementById("connectBtn").addEventListener("click", async () => {
  const fields = resolveConnectionFields();
  if (!fields) return;
  const { mode, backendUrl, projectSlug, sessionId, runId, extensionToken } = fields;

  const [activeTab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!activeTab) {
    setStatus("No active tab found.");
    return;
  }
  // chrome://, edge://, the Web Store, and other internal pages can
  // never accept an injected content script.
  if (!/^https?:\/\//.test(activeTab.url || "")) {
    setStatus("Switch to the target app tab first (not this browser page), then click the icon and try again.");
    return;
  }

  let backendOrigin;
  let targetOrigin;
  try {
    backendOrigin = new URL(backendUrl).origin + "/*";
    targetOrigin = new URL(activeTab.url).origin + "/*";
  } catch {
    setStatus("Backend or target-tab URL is not valid.");
    return;
  }

  // Explicit, narrow, user-gesture-driven permission request -- scoped
  // to the backend plus this one selected target origin. Persisting the
  // target-origin permission lets playback survive full-page navigation;
  // no wildcard/all-sites permission is requested.
  const granted = await chrome.permissions.request({ origins: [...new Set([backendOrigin, targetOrigin])] });
  if (!granted) {
    setStatus("Cannot connect without granting access to the QA-Again backend URL.");
    return;
  }

  setStatus("Connecting...");
  const resp = await chrome.runtime.sendMessage(
    mode === "playback"
      ? { type: "QA_EXT_ATTACH_PLAYBACK", backendUrl, projectSlug, runId, extensionToken, tabId: activeTab.id }
      : { type: "QA_EXT_CONNECT", backendUrl, projectSlug, sessionId, extensionToken, tabId: activeTab.id, targetUrl: activeTab.url },
  );

  if (resp?.ok) {
    if (mode === "playback") {
      showPlaybackConnected();
      setStatus(`Target selected. Use the floating controller in this tab to start ${resp.stepCount} action(s).`);
      setTimeout(() => window.close(), 700);
    } else {
      showConnected();
      setStatus(`Recording started on this tab. Session ${sessionId} is now RECORDING in QA-Again.`);
    }
  } else {
    setStatus(`Could not connect: ${resp.error || "unknown error"}`);
  }
});

document.getElementById("pauseBtn").addEventListener("click", async () => {
  const resp = await chrome.runtime.sendMessage({ type: "QA_EXT_PAUSE" });
  setStatus(resp.ok ? "Paused." : `Could not pause: ${resp.error}`);
});

document.getElementById("resumeBtn").addEventListener("click", async () => {
  const resp = await chrome.runtime.sendMessage({ type: "QA_EXT_RESUME" });
  setStatus(resp.ok ? "Recording resumed." : `Could not resume: ${resp.error}`);
});

document.getElementById("undoBtn").addEventListener("click", async () => {
  const resp = await chrome.runtime.sendMessage({ type: "QA_EXT_UNDO" });
  if (resp.ok) {
    const count = resp.session && resp.session.recorded_steps ? resp.session.recorded_steps.length : "?";
    setStatus(`Undid the last action. ${count} step(s) remain.`);
  } else {
    setStatus(`Could not undo: ${resp.error}`);
  }
});

document.getElementById("stopBtn").addEventListener("click", async () => {
  const resp = await chrome.runtime.sendMessage({ type: "QA_EXT_STOP" });
  if (resp.ok) {
    showDisconnected();
    setStatus("Stopped. Review and save the draft in QA-Again.");
  } else {
    setStatus(`Could not stop: ${resp.error}`);
  }
});

refreshStatus();
