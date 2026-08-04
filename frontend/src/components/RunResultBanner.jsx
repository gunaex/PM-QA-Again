// A single big "did it work" banner instead of making the tester parse
// a WorkflowRun status string -- the plain-language result Phase B was
// asked for. Shared between WorkflowDetail's real-run view and
// RecordingPanel's Phase E "Test It Now" preview-run view.
const RUN_BANNER = {
  WAITING_FOR_TARGET: { icon: '◎', label: 'CHOOSE TARGET TAB', tone: 'bg-amber-50 border-amber-200 text-amber-800' },
  READY: { icon: '✋', label: 'READY — PRESS START IN TARGET TAB', tone: 'bg-amber-50 border-amber-200 text-amber-800' },
  QUEUED: { icon: '⏳', label: 'PREPARING BROWSER', tone: 'bg-blue-50 border-blue-200 text-blue-800' },
  CLAIMED: { icon: '⏳', label: 'STARTING TEST', tone: 'bg-blue-50 border-blue-200 text-blue-800' },
  STARTING: { icon: '⏳', label: 'STARTING TEST', tone: 'bg-blue-50 border-blue-200 text-blue-800' },
  RUNNING: { icon: '▶', label: 'RUNNING', tone: 'bg-blue-50 border-blue-200 text-blue-800' },
  PASSED: { icon: '✅', label: 'PASSED', tone: 'bg-green-50 border-green-200 text-green-800' },
  FAILED: { icon: '❌', label: 'FAILED', tone: 'bg-red-50 border-red-200 text-red-800' },
  RUNNER_LOST: { icon: '❌', label: 'FAILED (browser session lost)', tone: 'bg-red-50 border-red-200 text-red-800' },
  SYSTEM_ERROR: { icon: '❌', label: 'FAILED (system error)', tone: 'bg-red-50 border-red-200 text-red-800' },
  BLOCKED: { icon: '🚫', label: 'BLOCKED', tone: 'bg-red-50 border-red-200 text-red-800' },
  NOT_APPLICABLE: { icon: '➖', label: 'NOT APPLICABLE', tone: 'bg-gray-50 border-gray-200 text-gray-600' },
  CANCELLED: { icon: '⏹️', label: 'CANCELLED', tone: 'bg-gray-50 border-gray-200 text-gray-600' },
  WAITING_FOR_HUMAN: { icon: '✋', label: 'WAITING FOR YOU', tone: 'bg-amber-50 border-amber-200 text-amber-800' },
  RESUMING: { icon: '✋', label: 'WAITING FOR YOU', tone: 'bg-amber-50 border-amber-200 text-amber-800' },
}

export default function RunResultBanner({ status }) {
  const entry = RUN_BANNER[status] || { icon: '⏳', label: 'RUNNING', tone: 'bg-blue-50 border-blue-200 text-blue-800' }
  return (
    <div className={`flex items-center gap-2 px-3 py-2 rounded-md border font-semibold text-sm ${entry.tone}`}>
      <span className="text-lg">{entry.icon}</span> {entry.label}
    </div>
  )
}
