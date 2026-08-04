// Draggable playback controller injected only into the tester-selected tab.
// It contains no test logic: the MV3 background worker owns execution so a
// full-page navigation cannot lose the run. This page-local controller only
// waits for the tester's explicit Start/Cancel gesture and shows progress.
(() => {
  const existing = document.getElementById("qa-again-playback-host");
  if (existing) existing.remove();

  const host = document.createElement("div");
  host.id = "qa-again-playback-host";
  host.style.cssText = "all:initial;position:fixed;top:18px;right:18px;z-index:2147483647";
  const shadow = host.attachShadow({ mode: "closed" });
  const style = document.createElement("style");
  style.textContent = `
    * { box-sizing: border-box; }
    .panel { width: 310px; border: 1px solid #a7f3d0; border-radius: 14px; background: #fff;
      color: #111827; box-shadow: 0 16px 45px rgba(0,0,0,.24); font: 13px/1.4 system-ui,sans-serif; overflow: hidden; }
    .head { cursor: move; user-select: none; padding: 10px 12px; background: #ecfdf5; border-bottom: 1px solid #d1fae5;
      display: flex; align-items: center; gap: 8px; font-weight: 700; color: #065f46; }
    .dot { width: 9px; height: 9px; border-radius: 50%; background: #10b981; }
    .body { padding: 12px; }
    .name { font-weight: 650; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .status { color: #6b7280; font-size: 12px; margin-top: 4px; min-height: 34px; }
    .progress { height: 5px; border-radius: 999px; background: #e5e7eb; overflow: hidden; margin: 10px 0; }
    .bar { height: 100%; width: 0; background: #10b981; transition: width .2s ease; }
    .row { display: flex; gap: 8px; }
    button { flex: 1; border: 0; border-radius: 8px; padding: 9px 10px; font: 600 12px system-ui,sans-serif; cursor: pointer; }
    .start { background: #059669; color: white; }
    .cancel { background: #fee2e2; color: #b91c1c; }
    button:disabled { opacity: .55; cursor: default; }
    .hint { margin-top: 8px; color: #9ca3af; font-size: 10px; text-align: center; }
  `;
  const panel = document.createElement("div");
  panel.className = "panel";
  const head = document.createElement("div");
  head.className = "head";
  const dot = document.createElement("span");
  dot.className = "dot";
  const headText = document.createElement("span");
  headText.textContent = "QA-Again Test Controller";
  head.append(dot, headText);
  const body = document.createElement("div");
  body.className = "body";
  const name = document.createElement("div");
  name.className = "name";
  name.textContent = "Automated test";
  const status = document.createElement("div");
  status.className = "status";
  status.textContent = "This tab is selected. Nothing runs until you press Start.";
  const progress = document.createElement("div");
  progress.className = "progress";
  const bar = document.createElement("div");
  bar.className = "bar";
  progress.append(bar);
  const row = document.createElement("div");
  row.className = "row";
  const start = document.createElement("button");
  start.className = "start";
  start.textContent = "Start Test";
  const cancel = document.createElement("button");
  cancel.className = "cancel";
  cancel.textContent = "Cancel";
  row.append(start, cancel);
  const hint = document.createElement("div");
  hint.className = "hint";
  hint.textContent = "Drag this panel anywhere before starting";
  body.append(name, status, progress, row, hint);
  panel.append(head, body);
  shadow.append(style, panel);
  document.documentElement.append(host);

  let dragging = false;
  let offsetX = 0;
  let offsetY = 0;
  head.addEventListener("pointerdown", (event) => {
    dragging = true;
    const rect = host.getBoundingClientRect();
    offsetX = event.clientX - rect.left;
    offsetY = event.clientY - rect.top;
    head.setPointerCapture(event.pointerId);
  });
  head.addEventListener("pointermove", (event) => {
    if (!dragging) return;
    const left = Math.max(0, Math.min(window.innerWidth - host.offsetWidth, event.clientX - offsetX));
    const top = Math.max(0, Math.min(window.innerHeight - host.offsetHeight, event.clientY - offsetY));
    host.style.left = `${left}px`;
    host.style.top = `${top}px`;
    host.style.right = "auto";
  });
  head.addEventListener("pointerup", () => { dragging = false; });

  start.addEventListener("click", () => {
    start.disabled = true;
    status.textContent = "Starting test…";
    chrome.runtime.sendMessage({ type: "QA_EXT_PLAYBACK_START" }, (response) => {
      if (chrome.runtime.lastError) {
        status.textContent = chrome.runtime.lastError.message;
        start.disabled = false;
        return;
      }
      if (response && !response.ok) {
        status.textContent = response.error || "Could not start this test.";
        start.disabled = false;
      }
    });
  });

  cancel.addEventListener("click", () => {
    start.disabled = true;
    cancel.disabled = true;
    status.textContent = "Cancelling…";
    chrome.runtime.sendMessage({ type: "QA_EXT_PLAYBACK_CANCEL" });
  });

  chrome.runtime.onMessage.addListener((message) => {
    if (message.type !== "QA_EXT_PLAYBACK_UI") return;
    if (message.workflowName) name.textContent = message.workflowName;
    if (message.message) status.textContent = message.message;
    if (typeof message.completed === "number" && typeof message.total === "number") {
      bar.style.width = `${message.total ? Math.round((message.completed / message.total) * 100) : 0}%`;
    }
    if (message.state === "READY") {
      start.disabled = false;
      cancel.disabled = false;
    } else if (message.state === "RUNNING") {
      start.disabled = true;
      cancel.disabled = false;
      start.textContent = "Running…";
    } else if (["PASSED", "FAILED", "CANCELLED"].includes(message.state)) {
      start.disabled = true;
      cancel.disabled = true;
      cancel.textContent = "Close";
      setTimeout(() => host.remove(), 3500);
    }
  });

  chrome.runtime.sendMessage({ type: "QA_EXT_PLAYBACK_OVERLAY_READY" });
})();
