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

async function refreshStatus() {
  const resp = await chrome.runtime.sendMessage({ type: "QA_EXT_STATUS" });
  if (resp && resp.config && resp.config.recording) {
    showConnected();
    setStatus(`Connected -- session ${resp.config.sessionId} on ${resp.config.backendUrl}`);
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
    if (!decoded.backendUrl || !decoded.projectSlug || !decoded.sessionId || !decoded.token) {
      setStatus("Pairing code is missing fields -- copy it again from QA-Again.");
      return null;
    }
    return {
      backendUrl: String(decoded.backendUrl),
      projectSlug: String(decoded.projectSlug),
      sessionId: String(decoded.sessionId),
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
  return { backendUrl, projectSlug, sessionId, extensionToken };
}

document.getElementById("connectBtn").addEventListener("click", async () => {
  const fields = resolveConnectionFields();
  if (!fields) return;
  const { backendUrl, projectSlug, sessionId, extensionToken } = fields;

  let origin;
  try {
    origin = new URL(backendUrl).origin + "/*";
  } catch {
    setStatus("Backend URL is not valid.");
    return;
  }

  // Explicit, narrow, user-gesture-driven permission request -- scoped
  // to exactly the one backend origin the tester just typed in, shown
  // to them as a real Chrome permission prompt naming that origin.
  // Nothing broader is ever requested.
  const granted = await chrome.permissions.request({ origins: [origin] });
  if (!granted) {
    setStatus("Cannot record without granting access to the backend URL you entered.");
    return;
  }

  const [activeTab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!activeTab) {
    setStatus("No active tab found.");
    return;
  }
  // chrome://, edge://, the Web Store, and other internal pages can
  // never accept an injected content script -- Chrome blocks this
  // unconditionally, regardless of any permission granted above. Catch
  // it here with a clear, actionable message instead of surfacing the
  // raw "Cannot access a chrome:// URL" error from background.js.
  if (!/^https?:\/\//.test(activeTab.url || "")) {
    setStatus("Switch to the tab with the app you want to record first (not this browser page), then click the icon and try again.");
    return;
  }

  setStatus("Connecting...");
  const resp = await chrome.runtime.sendMessage({
    type: "QA_EXT_CONNECT",
    backendUrl,
    projectSlug,
    sessionId,
    extensionToken,
    tabId: activeTab.id,
  });

  if (resp.ok) {
    showConnected();
    setStatus(`Recording started on this tab. Session ${sessionId} is now RECORDING in QA-Again.`);
  } else {
    setStatus(`Could not start recording: ${resp.error || "unknown error"}`);
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
