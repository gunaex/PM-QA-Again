/** HYB-3 in-page recorder script -- runs INSIDE the Playwright-controlled
 * page the QA Runner itself launched, injected via page.addInitScript()
 * so it re-attaches on every navigation within the same recording
 * session. This is the entire surface that "records": document-level
 * event listeners for click/change/keydown, nothing else. There is no
 * mousemove listener anywhere in this file (never recorded), no global
 * OS hook (impossible from page JS anyway -- this only ever sees events
 * inside this one page), and no focus/blur listener (change already
 * fires once per edit session, which is what "one FILL step per field"
 * needs).
 *
 * Emits structured events to Node via `window.__qaRecorderEmit`, a
 * function the Node side exposes with `page.exposeFunction`. A
 * sensitive field's real value is NEVER included in the emitted
 * payload -- the redaction happens here, in-page, before the value
 * would ever cross the bridge into Node's process, let alone reach the
 * backend or a log line.
 */

export const RECORDER_INIT_SCRIPT = `
(() => {
  if (window.__qaRecorderInstalled) return;
  window.__qaRecorderInstalled = true;
  window.__qaRecorderPaused = false;

  const SENSITIVE_PATTERN = /password|passwd|secret|otp|one[-_ ]?time|token|cvv|card[-_ ]?number|pin\\b/i;

  function isSensitive(el) {
    if (!el) return false;
    const type = (el.type || '').toLowerCase();
    if (type === 'password') return true;
    const autocomplete = (el.getAttribute('autocomplete') || '').toLowerCase();
    if (/password|cc-|one-time-code/.test(autocomplete)) return true;
    const probe = [el.name, el.id, el.getAttribute('aria-label'), el.placeholder].join(' ');
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
    const parentLabel = el.closest('label');
    if (parentLabel) return parentLabel.textContent.trim();
    const ariaLabel = el.getAttribute('aria-label');
    if (ariaLabel) return ariaLabel.trim();
    return null;
  }

  /** Real accessible-name computation (and Playwright's getByRole name
   * matching) treats text from different child nodes/elements as
   * separated by whitespace -- raw el.textContent does NOT insert that
   * whitespace between adjacent elements with no literal space between
   * them in the source markup, so a multi-element button (e.g. a card
   * with a title, a date, and nested action buttons) produces a
   * run-together string that fails to match at replay. Found via this
   * session's real end-to-end replay, not by inspection. This walks
   * the subtree and joins each text node's trimmed content with a
   * single space, matching how the browser actually flattens it. */
  function flatText(el) {
    const parts = [];
    (function walk(node) {
      if (node.nodeType === 3) {
        const t = node.textContent.trim();
        if (t) parts.push(t);
      } else if (node.nodeType === 1) {
        if (node.hidden || node.getAttribute('aria-hidden') === 'true') return;
        for (const child of node.childNodes) walk(child);
      }
    })(el);
    return parts.join(' ').replace(/\\s+/g, ' ').trim();
  }

  function accessibleRole(el) {
    const explicit = el.getAttribute('role');
    if (explicit) return explicit;
    const tag = el.tagName.toLowerCase();
    if (tag === 'button') return 'button';
    if (tag === 'a' && el.hasAttribute('href')) return 'link';
    if (tag === 'input') {
      const t = (el.type || 'text').toLowerCase();
      if (t === 'submit' || t === 'button') return 'button';
      if (t === 'checkbox') return 'checkbox';
      if (t === 'radio') return 'radio';
      return 'textbox';
    }
    if (tag === 'select') return 'combobox';
    if (tag === 'textarea') return 'textbox';
    return null;
  }

  function accessibleName(el) {
    const ariaLabel = el.getAttribute('aria-label');
    if (ariaLabel) return ariaLabel.trim();
    const label = labelFor(el);
    if (label) return label;
    // textContent is only meaningful as a name source for elements whose
    // visible text IS their identity (buttons, links) -- for a form
    // control (select/input/textarea) it would concatenate unrelated
    // descendant text (e.g. every <option> inside a <select>), which is
    // not how real accessible-name computation works and would not
    // reliably resolve at replay. A form control with no aria-label and
    // no associated <label> has no reliable ROLE name -- fall through
    // to another strategy instead of guessing.
    const tag = el.tagName.toLowerCase();
    if (tag === 'select' || tag === 'input' || tag === 'textarea') return null;
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

  /** Ranked locator strategies, exactly the priority order this app
   * documents everywhere else (models.LOCATOR_STRATEGIES): test id ->
   * role+name -> label -> stable attribute -> stable text -> CSS ->
   * XPath. Returns {strategy, value, fallbacks, warnings}. */
  function computeLocator(el) {
    const candidates = [];
    const warnings = [];

    const testId = el.getAttribute('data-testid') || el.getAttribute('data-test-id') || el.getAttribute('data-qa');
    if (testId) {
      candidates.push({
        strategy: 'TEST_ID', value: testId,
        unique: isUnique(() => document.querySelectorAll('[data-testid="' + CSS.escape(testId) + '"],[data-test-id="' + CSS.escape(testId) + '"],[data-qa="' + CSS.escape(testId) + '"]')),
      });
    }

    const role = accessibleRole(el);
    const name = accessibleName(el);
    if (role && name) {
      candidates.push({ strategy: 'ROLE', value: role + ':' + name, unique: true }); // uniqueness genuinely verified at replay time via Playwright's own getByRole
    }

    const label = labelFor(el);
    if (label) {
      candidates.push({ strategy: 'LABEL', value: label, unique: true });
    }

    const placeholder = el.placeholder;
    if (placeholder) {
      candidates.push({
        strategy: 'PLACEHOLDER', value: placeholder,
        unique: isUnique(() => document.querySelectorAll('[placeholder="' + CSS.escape(placeholder) + '"]')),
      });
    }

    // Same reasoning as accessibleName(): a form control's textContent
    // (e.g. every <option> inside a <select>) is not meaningful visible
    // text for locating the control itself -- only consider this
    // fallback for elements where visible text IS the element's identity.
    const isFormControl = el.tagName === 'SELECT' || el.tagName === 'INPUT' || el.tagName === 'TEXTAREA';
    const text = isFormControl ? '' : flatText(el);
    if (text && text.length > 0 && text.length <= 60 && candidates.length === 0) {
      candidates.push({ strategy: 'TEXT', value: text, unique: false });
      warnings.push('No test id, role+name, label, or placeholder found -- falling back to visible text, which is not guaranteed unique.');
    }

    if (candidates.length === 0) {
      const cssPath = cssPathFor(el);
      candidates.push({ strategy: 'CSS', value: cssPath, unique: true });
      warnings.push('No semantic locator found (no test id, accessible role/name, label, placeholder, or short text) -- using a structural CSS path. This is fragile against layout changes; consider adding a data-testid.');
    }

    if (!candidates[0].unique && candidates[0].strategy !== 'ROLE' && candidates[0].strategy !== 'LABEL') {
      warnings.push('Primary locator candidate (' + candidates[0].strategy + ') did not resolve to exactly one element at capture time.');
    }

    const primary = candidates[0];
    const fallbacks = candidates.slice(1).map((c) => ({ strategy: c.strategy, value: c.value }));
    return { strategy: primary.strategy, value: primary.value, fallbacks, warnings };
  }

  function cssPathFor(el) {
    if (el.id) return '#' + CSS.escape(el.id);
    const parts = [];
    let node = el;
    while (node && node.nodeType === 1 && parts.length < 6) {
      let selector = node.tagName.toLowerCase();
      const parent = node.parentElement;
      if (parent) {
        const siblings = Array.from(parent.children).filter((c) => c.tagName === node.tagName);
        if (siblings.length > 1) {
          selector += ':nth-of-type(' + (siblings.indexOf(node) + 1) + ')';
        }
      }
      parts.unshift(selector);
      node = parent;
    }
    return parts.join(' > ');
  }

  function targetSummary(el) {
    const tag = el.tagName.toLowerCase();
    const text = (el.textContent || '').trim().slice(0, 60);
    return '<' + tag + (el.type ? ' type="' + el.type + '"' : '') + '>' + (text ? text : '') + (tag !== 'input' && tag !== 'select' ? '</' + tag + '>' : '');
  }

  // Two DOM events captured in quick succession (e.g. a field's 'change'
  // firing on blur immediately followed by a 'click' on the next
  // control) each trigger an independent async round trip to Node/the
  // backend. Without serializing them, whichever network call happens
  // to complete first determines persisted order -- not the order the
  // events actually occurred in the page. This FIFO chain guarantees
  // the backend receives them in true capture order regardless of
  // individual network timing. Found via this session's real recording
  // (a password FILL and the following Sign-in CLICK were persisted out
  // of order), not by inspection.
  let emitQueue = Promise.resolve();
  function emit(payload) {
    if (window.__qaRecorderPaused) return;
    emitQueue = emitQueue.then(() => {
      if (typeof window.__qaRecorderEmit === 'function') {
        return window.__qaRecorderEmit(Object.assign({ pageContext: location.pathname }, payload));
      }
    });
    return emitQueue;
  }

  const INTERACTIVE_SELECTOR = 'button, a[href], [role="button"], [role="link"], input[type="submit"], input[type="button"], input[type="checkbox"], input[type="radio"], label';

  document.addEventListener(
    'click',
    (e) => {
      let el = e.target;
      if (el && el.closest) el = el.closest(INTERACTIVE_SELECTOR) || el;
      if (!el || !el.matches || !el.matches(INTERACTIVE_SELECTOR)) return;
      if (el.tagName === 'INPUT' && (el.type === 'checkbox' || el.type === 'radio')) return; // handled by 'change' instead
      const loc = computeLocator(el);
      emit({
        stepType: 'CLICK', locatorStrategy: loc.strategy, locatorValue: loc.value,
        locatorFallbacks: loc.fallbacks, locatorWarnings: loc.warnings,
        targetSummary: targetSummary(el), diagnosticX: Math.round(e.clientX), diagnosticY: Math.round(e.clientY),
      });
    },
    true,
  );

  document.addEventListener(
    'change',
    (e) => {
      const el = e.target;
      if (!el || !el.tagName) return;
      const tag = el.tagName.toLowerCase();
      const loc = computeLocator(el);

      if (tag === 'select') {
        emit({
          stepType: 'SELECT', locatorStrategy: loc.strategy, locatorValue: loc.value,
          locatorFallbacks: loc.fallbacks, locatorWarnings: loc.warnings,
          targetSummary: targetSummary(el), inputValue: el.options[el.selectedIndex] ? el.options[el.selectedIndex].text : el.value,
        });
        return;
      }

      if (tag === 'input' && el.type === 'checkbox') {
        emit({
          stepType: el.checked ? 'CHECK' : 'UNCHECK', locatorStrategy: loc.strategy, locatorValue: loc.value,
          locatorFallbacks: loc.fallbacks, locatorWarnings: loc.warnings, targetSummary: targetSummary(el),
        });
        return;
      }

      if (tag === 'input' && el.type === 'radio') {
        emit({
          stepType: 'CLICK', locatorStrategy: loc.strategy, locatorValue: loc.value,
          locatorFallbacks: loc.fallbacks, locatorWarnings: loc.warnings, targetSummary: targetSummary(el),
        });
        return;
      }

      if (tag === 'input' && el.type === 'file') {
        // File-upload INTENT only -- the real local path never leaves
        // this branch, not even the filename crosses the bridge.
        emit({
          stepType: 'MANUAL_CHECKPOINT',
          checkpointInstructions: 'Recorder detected a file selection here. File uploads are not automated in this MVP (no local file path is ever recorded) -- attach the file manually at this step, or extend the workflow model in a later phase.',
          targetSummary: targetSummary(el), needsReview: true,
          reviewNote: 'Recorded as a manual checkpoint because file-upload automation is out of scope for the recorder MVP.',
        });
        return;
      }

      if (tag === 'input' || tag === 'textarea') {
        const sensitive = isSensitive(el);
        emit({
          stepType: 'FILL', locatorStrategy: loc.strategy, locatorValue: loc.value,
          locatorFallbacks: loc.fallbacks, locatorWarnings: loc.warnings, targetSummary: targetSummary(el),
          isSensitive: sensitive,
          // Deliberately omitted entirely (not even an empty string) for
          // a sensitive field -- see the module docstring.
          inputValue: sensitive ? undefined : el.value,
        });
      }
    },
    true,
  );

  document.addEventListener(
    'keydown',
    (e) => {
      if (window.__qaRecorderPaused) return;
      if (!['Enter', 'Escape'].includes(e.key)) return;
      const el = e.target;
      const tag = el && el.tagName ? el.tagName.toLowerCase() : '';
      // Enter inside a text field is normally form submission, already
      // implied by the FILL + the eventual navigation/CLICK -- only
      // record it as its own PRESS_KEY step for non-field targets
      // (e.g. Escape to close a modal), avoiding one redundant step per
      // Enter-to-submit.
      if (tag === 'input' || tag === 'textarea') return;
      emit({ stepType: 'PRESS_KEY', inputValue: e.key, targetSummary: targetSummary(el || document.body) });
    },
    true,
  );
})();
`;
