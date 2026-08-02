// QA-Again Chrome extension recorder -- content script.
//
// Injected on demand via chrome.scripting.executeScript (activeTab-gated,
// only after the user clicked "Start Recording" in the popup -- never
// declared as a manifest content_script, never runs automatically on
// page load). Ports the exact same locator-priority and redaction logic
// as runner/src/recorder/domRecorder.ts (the Playwright-mode recorder)
// so both recording modes produce structurally identical RecordedStep
// data -- same locator vocabulary, same sensitive-field handling, same
// noise-reduction (needs_review flags), never a second, divergent
// recording behavior.
//
// This script has NO visibility into cookies, localStorage/
// sessionStorage, or HTTP headers -- content scripts simply cannot see
// those (no `cookies` permission, no `webRequest` permission is declared
// anywhere in this extension). It attaches only ordinary DOM event
// listeners (click/change/keydown) to this one document -- never a
// global OS-level input hook, which is impossible from page JS/content-
// script context anyway.

(() => {
  if (window.__qaExtRecorderInstalled) return;
  window.__qaExtRecorderInstalled = true;
  window.__qaExtRecorderPaused = false;

  const SENSITIVE_PATTERN = /password|passwd|secret|otp|one[-_ ]?time|token|cvv|card[-_ ]?number|pin\b/i;

  function isSensitive(el) {
    if (!el) return false;
    const type = (el.type || "").toLowerCase();
    if (type === "password") return true;
    const autocomplete = (el.getAttribute("autocomplete") || "").toLowerCase();
    if (/password|cc-|one-time-code/.test(autocomplete)) return true;
    const probe = [el.name, el.id, el.getAttribute("aria-label"), el.placeholder].join(" ");
    if (SENSITIVE_PATTERN.test(probe)) return true;
    const label = labelFor(el);
    if (label && SENSITIVE_PATTERN.test(label)) return true;
    return false;
  }

  function labelFor(el) {
    if (el.id) {
      const byFor = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
      if (byFor) return byFor.textContent.trim();
    }
    const parentLabel = el.closest("label");
    if (parentLabel) return parentLabel.textContent.trim();
    const ariaLabel = el.getAttribute("aria-label");
    if (ariaLabel) return ariaLabel.trim();
    return null;
  }

  function flatText(el) {
    const parts = [];
    (function walk(node) {
      if (node.nodeType === 3) {
        const t = node.textContent.trim();
        if (t) parts.push(t);
      } else if (node.nodeType === 1) {
        if (node.hidden || node.getAttribute("aria-hidden") === "true") return;
        for (const child of node.childNodes) walk(child);
      }
    })(el);
    return parts.join(" ").replace(/\s+/g, " ").trim();
  }

  function accessibleRole(el) {
    const explicit = el.getAttribute("role");
    if (explicit) return explicit;
    const tag = el.tagName.toLowerCase();
    if (tag === "button") return "button";
    if (tag === "a" && el.hasAttribute("href")) return "link";
    if (tag === "input") {
      const t = (el.type || "text").toLowerCase();
      if (t === "submit" || t === "button") return "button";
      if (t === "checkbox") return "checkbox";
      if (t === "radio") return "radio";
      return "textbox";
    }
    if (tag === "select") return "combobox";
    if (tag === "textarea") return "textbox";
    return null;
  }

  function accessibleName(el) {
    const ariaLabel = el.getAttribute("aria-label");
    if (ariaLabel) return ariaLabel.trim();
    const label = labelFor(el);
    if (label) return label;
    const tag = el.tagName.toLowerCase();
    if (tag === "select" || tag === "input" || tag === "textarea") return null;
    const text = flatText(el);
    if (text && text.length <= 80) return text;
    return null;
  }

  function isUnique(selectorFn) {
    try {
      const matches = selectorFn();
      return matches != null && matches.length === 1;
    } catch {
      return false;
    }
  }

  // Ranked locator strategies -- exactly the priority order this app
  // documents everywhere else (backend LOCATOR_STRATEGIES / ADR-HYB-002):
  // data-testid -> role+name -> label -> stable attribute -> stable text
  // -> CSS. Never raw X/Y as the primary locator.
  function computeLocator(el) {
    const candidates = [];
    const warnings = [];

    const testId = el.getAttribute("data-testid") || el.getAttribute("data-test-id") || el.getAttribute("data-qa");
    if (testId) {
      candidates.push({
        strategy: "TEST_ID",
        value: testId,
        unique: isUnique(() =>
          document.querySelectorAll(
            '[data-testid="' + CSS.escape(testId) + '"],[data-test-id="' + CSS.escape(testId) + '"],[data-qa="' + CSS.escape(testId) + '"]',
          ),
        ),
      });
    }

    const role = accessibleRole(el);
    const name = accessibleName(el);
    if (role && name) {
      candidates.push({ strategy: "ROLE", value: role + ":" + name, unique: true });
    }

    const label = labelFor(el);
    if (label) {
      candidates.push({ strategy: "LABEL", value: label, unique: true });
    }

    const placeholder = el.placeholder;
    if (placeholder) {
      candidates.push({
        strategy: "PLACEHOLDER",
        value: placeholder,
        unique: isUnique(() => document.querySelectorAll('[placeholder="' + CSS.escape(placeholder) + '"]')),
      });
    }

    const isFormControl = el.tagName === "SELECT" || el.tagName === "INPUT" || el.tagName === "TEXTAREA";
    const text = isFormControl ? "" : flatText(el);
    if (text && text.length > 0 && text.length <= 60 && candidates.length === 0) {
      candidates.push({ strategy: "TEXT", value: text, unique: false });
      warnings.push("No test id, role+name, label, or placeholder found -- falling back to visible text, which is not guaranteed unique.");
    }

    if (candidates.length === 0) {
      const cssPath = cssPathFor(el);
      candidates.push({ strategy: "CSS", value: cssPath, unique: true });
      warnings.push(
        "No semantic locator found (no test id, accessible role/name, label, placeholder, or short text) -- using a structural CSS path. This is fragile against layout changes; consider adding a data-testid.",
      );
    }

    if (!candidates[0].unique && candidates[0].strategy !== "ROLE" && candidates[0].strategy !== "LABEL") {
      warnings.push("Primary locator candidate (" + candidates[0].strategy + ") did not resolve to exactly one element at capture time.");
    }

    const primary = candidates[0];
    const fallbacks = candidates.slice(1).map((c) => ({ strategy: c.strategy, value: c.value }));
    return { strategy: primary.strategy, value: primary.value, fallbacks, warnings };
  }

  function cssPathFor(el) {
    if (el.id) return "#" + CSS.escape(el.id);
    const parts = [];
    let node = el;
    while (node && node.nodeType === 1 && parts.length < 6) {
      let selector = node.tagName.toLowerCase();
      const parent = node.parentElement;
      if (parent) {
        const siblings = Array.from(parent.children).filter((c) => c.tagName === node.tagName);
        if (siblings.length > 1) {
          selector += ":nth-of-type(" + (siblings.indexOf(node) + 1) + ")";
        }
      }
      parts.unshift(selector);
      node = parent;
    }
    return parts.join(" > ");
  }

  function targetSummary(el) {
    const tag = el.tagName.toLowerCase();
    const text = (el.textContent || "").trim().slice(0, 60);
    return "<" + tag + (el.type ? ' type="' + el.type + '"' : "") + ">" + (text ? text : "") + (tag !== "input" && tag !== "select" ? "</" + tag + ">" : "");
  }

  // Same FIFO-serialization discipline as the Playwright recorder --
  // two events captured in quick succession must reach the background
  // (and the backend) in true capture order, not whichever async
  // round-trip happens to finish first.
  let emitQueue = Promise.resolve();
  function emit(payload) {
    if (window.__qaExtRecorderPaused) return;
    emitQueue = emitQueue.then(
      () =>
        new Promise((resolve) => {
          chrome.runtime.sendMessage(
            { type: "QA_EXT_RECORDED_EVENT", payload: Object.assign({ pageContext: location.pathname }, payload) },
            () => resolve(),
          );
        }),
    );
    return emitQueue;
  }

  const INTERACTIVE_SELECTOR =
    'button, a[href], [role="button"], [role="link"], input[type="submit"], input[type="button"], input[type="checkbox"], input[type="radio"], label';

  document.addEventListener(
    "click",
    (e) => {
      let el = e.target;
      if (el && el.closest) el = el.closest(INTERACTIVE_SELECTOR) || el;
      if (!el || !el.matches || !el.matches(INTERACTIVE_SELECTOR)) return;
      if (el.tagName === "INPUT" && (el.type === "checkbox" || el.type === "radio")) return; // handled by 'change' instead
      const loc = computeLocator(el);
      emit({
        stepType: "CLICK",
        locatorStrategy: loc.strategy,
        locatorValue: loc.value,
        locatorFallbacks: loc.fallbacks,
        locatorWarnings: loc.warnings,
        targetSummary: targetSummary(el),
        // Diagnostic metadata ONLY -- never the primary locator, never
        // resolved against during replay.
        diagnosticX: Math.round(e.clientX),
        diagnosticY: Math.round(e.clientY),
      });
    },
    true,
  );

  document.addEventListener(
    "change",
    (e) => {
      const el = e.target;
      if (!el || !el.tagName) return;
      const tag = el.tagName.toLowerCase();
      const loc = computeLocator(el);

      if (tag === "select") {
        emit({
          stepType: "SELECT",
          locatorStrategy: loc.strategy,
          locatorValue: loc.value,
          locatorFallbacks: loc.fallbacks,
          locatorWarnings: loc.warnings,
          targetSummary: targetSummary(el),
          inputValue: el.options[el.selectedIndex] ? el.options[el.selectedIndex].text : el.value,
        });
        return;
      }

      if (tag === "input" && el.type === "checkbox") {
        emit({
          stepType: el.checked ? "CHECK" : "UNCHECK",
          locatorStrategy: loc.strategy,
          locatorValue: loc.value,
          locatorFallbacks: loc.fallbacks,
          locatorWarnings: loc.warnings,
          targetSummary: targetSummary(el),
        });
        return;
      }

      if (tag === "input" && el.type === "radio") {
        emit({
          stepType: "CLICK",
          locatorStrategy: loc.strategy,
          locatorValue: loc.value,
          locatorFallbacks: loc.fallbacks,
          locatorWarnings: loc.warnings,
          targetSummary: targetSummary(el),
        });
        return;
      }

      if (tag === "input" && el.type === "file") {
        // File-upload INTENT only -- the real local file path never
        // leaves this branch, not even the filename is recorded.
        emit({
          stepType: "MANUAL_CHECKPOINT",
          checkpointInstructions:
            "Recorder detected a file selection here. File uploads are not automated (no local file path is ever recorded) -- attach the file manually at this step.",
          targetSummary: targetSummary(el),
          needsReview: true,
          reviewNote: "Recorded as a manual checkpoint because file-upload automation is out of scope for the recorder.",
        });
        return;
      }

      if (tag === "input" || tag === "textarea") {
        const sensitive = isSensitive(el);
        emit({
          stepType: "FILL",
          locatorStrategy: loc.strategy,
          locatorValue: loc.value,
          locatorFallbacks: loc.fallbacks,
          locatorWarnings: loc.warnings,
          targetSummary: targetSummary(el),
          isSensitive: sensitive,
          // Deliberately omitted entirely for a sensitive field -- the
          // real value never leaves this content script, not even as an
          // empty-string placeholder that might invite confusion.
          inputValue: sensitive ? undefined : el.value,
        });
      }
    },
    true,
  );

  document.addEventListener(
    "submit",
    (e) => {
      const form = e.target;
      emit({
        stepType: "PRESS_KEY",
        inputValue: "Enter",
        targetSummary: "<form> submitted" + (form && form.id ? " #" + form.id : ""),
        description: "Form submission",
      });
    },
    true,
  );

  document.addEventListener(
    "keydown",
    (e) => {
      if (window.__qaExtRecorderPaused) return;
      if (!["Enter", "Escape"].includes(e.key)) return;
      const el = e.target;
      const tag = el && el.tagName ? el.tagName.toLowerCase() : "";
      // Enter inside a text field is normally form submission, already
      // captured by the 'submit' listener above -- only record it as
      // its own PRESS_KEY step for non-field targets (e.g. Escape to
      // close a modal), avoiding one redundant step per Enter-to-submit.
      if (tag === "input" || tag === "textarea") return;
      emit({ stepType: "PRESS_KEY", inputValue: e.key, targetSummary: targetSummary(el || document.body) });
    },
    true,
  );

  // Real navigation is reported by the background service worker
  // (chrome.tabs.onUpdated on the authorized tab), not from here --
  // this content script is re-injected fresh on every full-page
  // navigation, so it has no memory of "was this the first load".

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message.type === "QA_EXT_SET_PAUSED") {
      window.__qaExtRecorderPaused = !!message.paused;
      sendResponse({ ok: true });
    }
  });
})();
