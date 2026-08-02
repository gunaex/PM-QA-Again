// Converts a raw workflow/recorded step's technical fields into a
// plain-language sentence + icon -- e.g. "CLICK ROLE=button:Login"
// becomes "Click the Login button". Used everywhere a step is shown to
// a tester (RecordingPanel, WorkflowDetail's step/step-run lists,
// CheckpointPanel's prior-step-results) so the exact same phrasing
// appears during recording, review, and results.
//
// Best-effort only -- never a source of truth. The raw fields (visible
// behind a "Show Developer Data"-style toggle wherever this is used)
// are what the runner actually executes against.

// TEST_ID/LABEL/PLACEHOLDER/TEXT locator values are already
// human-readable as captured (see extension/content.js). ROLE values
// are "role:accessible name" (e.g. "button:Login") -- split and use
// just the name. CSS/XPATH are generated selectors, not meant for
// humans -- described generically instead of shown raw.
function describeLocator(strategy, value) {
  if (!value) return 'an element'
  if (strategy === 'ROLE') {
    const name = value.includes(':') ? value.split(':').slice(1).join(':') : value
    return name ? `the "${name}" control` : 'a control'
  }
  if (strategy === 'CSS' || strategy === 'XPATH') return 'an element (technical selector)'
  return `"${value}"`
}

const MS_PER_UNIT = [
  [3600000, 'hour'],
  [60000, 'minute'],
  [1000, 'second'],
]

function describeDuration(ms) {
  const n = Number(ms)
  if (!Number.isFinite(n) || n <= 0) return `${ms ?? '?'} ms`
  for (const [unit, label] of MS_PER_UNIT) {
    if (n >= unit) {
      const count = Math.round((n / unit) * 10) / 10
      return `${count} ${label}${count === 1 ? '' : 's'}`
    }
  }
  return `${n} ms`
}

// Shared icon set for a WorkflowStepRun's status -- used everywhere a
// step-run result is shown (WorkflowDetail's run detail, CheckpointPanel's
// prior-step-results) so PASSED/FAILED/etc. always render the same way.
export const STEP_RUN_ICON = { PASSED: '✅', FAILED: '❌', RUNNING: '⏳', PENDING: '⚪', SKIPPED: '➖' }

/**
 * @param {object} step - any of {step_type, locator_strategy,
 *   locator_value, input_value, expected_value, checkpoint_instructions}
 * @returns {{icon: string, text: string}}
 */
export function describeStep(step) {
  const { step_type: type, locator_strategy: strategy, locator_value: value, input_value, expected_value, checkpoint_instructions, repeat_count: repeatCount } = step || {}
  const el = () => describeLocator(strategy, value)
  const suffix = repeatCount > 1 ? ` (×${repeatCount})` : ''
  const withSuffix = (d) => ({ ...d, text: `${d.text}${suffix}` })

  switch (type) {
    case 'NAVIGATE':
      return { icon: '🧭', text: `Go to ${input_value || 'a page'}` }
    case 'CLICK':
      return withSuffix({ icon: '🖱️', text: `Click ${el()}` })
    case 'FILL':
      return withSuffix({ icon: '⌨️', text: `Type into ${el()}` })
    case 'SELECT':
      return withSuffix({ icon: '⌨️', text: `Choose "${input_value || '?'}" in ${el()}` })
    case 'CHECK':
      return withSuffix({ icon: '☑️', text: `Check ${el()}` })
    case 'UNCHECK':
      return withSuffix({ icon: '⬜', text: `Uncheck ${el()}` })
    case 'PRESS_KEY':
      return withSuffix({ icon: '⌨️', text: `Press "${input_value || 'Enter'}"${value ? ` in ${el()}` : ''}` })
    case 'WAIT_FOR_ELEMENT':
      return { icon: '⏳', text: `Wait for ${el()} to appear` }
    case 'WAIT':
      return { icon: '⏱️', text: `Wait ${describeDuration(input_value)}` }
    case 'ASSERT_VISIBLE':
      return withSuffix({ icon: '👁️', text: `Check that ${el()} is visible` })
    case 'ASSERT_TEXT':
      return withSuffix({ icon: '👁️', text: `Check the page shows "${expected_value || '?'}"` })
    case 'ASSERT_URL':
      return withSuffix({ icon: '👁️', text: `Check the page URL contains "${expected_value || '?'}"` })
    case 'SCREENSHOT':
      return withSuffix({ icon: '📸', text: 'Take a screenshot' })
    case 'MANUAL_CHECKPOINT':
      return { icon: '✋', text: checkpoint_instructions ? `Pause for you: ${checkpoint_instructions}` : 'Pause for a manual check' }
    default:
      return { icon: '❓', text: type || 'Unknown step' }
  }
}
