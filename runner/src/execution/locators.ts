import type { Page, Locator } from "playwright";
import type { ClaimedStep } from "../api/executionClient.js";

/** Structured-locator resolution -- never raw x/y. Priority/format
 * mirrors backend/app/models.py's LOCATOR_STRATEGIES and the
 * WorkflowDetail.jsx editor's own encoding (ROLE values are
 * "role:accessibleName", e.g. "button:Sign in"). */
export function resolveLocator(page: Page, step: ClaimedStep): Locator {
  const strategy = step.locator_strategy;
  const value = step.locator_value ?? "";
  switch (strategy) {
    case "TEST_ID":
      return page.getByTestId(value);
    case "ROLE": {
      const sep = value.indexOf(":");
      const role = sep === -1 ? value : value.slice(0, sep);
      const name = sep === -1 ? undefined : value.slice(sep + 1);
      return name ? page.getByRole(role as any, { name }) : page.getByRole(role as any);
    }
    case "LABEL":
      return page.getByLabel(value);
    case "PLACEHOLDER":
      return page.getByPlaceholder(value);
    case "TEXT":
      return page.getByText(value);
    case "CSS":
      return page.locator(value);
    case "XPATH":
      return page.locator(`xpath=${value}`);
    default:
      throw new Error(`Unknown or missing locator_strategy: ${strategy}`);
  }
}

/** Resolves "${VAR_NAME}" against the runner's own environment. Never
 * logs the resolved value for a sensitive step -- callers must not
 * include the return value of this function in any event payload,
 * screenshot caption, or log line when step.is_sensitive is true. */
export function resolveValue(step: ClaimedStep): string {
  const raw = step.input_value ?? "";
  const match = raw.match(/^\$\{([A-Z][A-Z0-9_]*)\}$/);
  if (!match) return raw;
  const varName = match[1];
  const value = process.env[varName];
  if (value === undefined) {
    throw new Error(
      `Missing runner environment variable ${varName} required by this workflow step` +
        (step.is_sensitive ? " (sensitive value -- set it in the runner's own environment, never in the workflow)" : ""),
    );
  }
  return value;
}

/** Heuristic failure categorization -- one of backend's FAILURE_CATEGORIES.
 * Never invents ASSERTION_FAILED for a locator problem or vice versa. */
export function categorizeError(stepType: string, err: unknown): string {
  const message = String((err as Error)?.message ?? err);
  if (/Target (page|context|browser) has been closed|crashed/i.test(message)) return "BROWSER_CRASH";
  if (stepType === "NAVIGATE") return "NAVIGATION_ERROR";
  if (stepType.startsWith("ASSERT")) return "ASSERTION_FAILED";
  if (/strict mode violation|resolved to \d+ elements/i.test(message)) return "LOCATOR_AMBIGUOUS";
  if (/Timeout \d+ms exceeded/i.test(message)) return "TIMEOUT";
  if (/waiting for (locator|selector)|element.*not found|no element/i.test(message)) return "LOCATOR_NOT_FOUND";
  if (/Missing runner environment variable/i.test(message)) return "INPUT_ERROR";
  return "SYSTEM_ERROR";
}
