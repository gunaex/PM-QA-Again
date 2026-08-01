const STYLES = {
  // Suites
  ACTIVE: 'bg-green-100 text-green-700',
  ARCHIVED: 'bg-gray-100 text-gray-600',
  // Revisions
  DRAFT: 'bg-gray-100 text-gray-600',
  PUBLISHED: 'bg-green-100 text-green-700',
  SUPERSEDED: 'bg-yellow-100 text-yellow-700',
  // Test results
  PASS: 'bg-green-100 text-green-700',
  FAIL: 'bg-red-100 text-red-700',
  BLOCKED: 'bg-red-100 text-red-700',
  NOT_RUN: 'bg-gray-100 text-gray-600',
  NOT_APPLICABLE: 'bg-yellow-100 text-yellow-700',
  // Cycles
  READY: 'bg-blue-100 text-blue-700',
  IN_PROGRESS: 'bg-blue-100 text-blue-700',
  REVIEW: 'bg-yellow-100 text-yellow-700',
  COMPLETED: 'bg-green-100 text-green-700',
  LOCKED: 'bg-gray-200 text-gray-700',
  CANCELLED: 'bg-red-100 text-red-700',
  // Review status
  UNREVIEWED: 'bg-gray-100 text-gray-600',
  ACCEPTED: 'bg-green-100 text-green-700',
  CHANGES_REQUESTED: 'bg-red-100 text-red-700',
  // Workflow runs (HYB-2/HYB-4)
  QUEUED: 'bg-gray-100 text-gray-600',
  CLAIMED: 'bg-blue-100 text-blue-700',
  STARTING: 'bg-blue-100 text-blue-700',
  RUNNING: 'bg-blue-100 text-blue-700',
  PASSED: 'bg-green-100 text-green-700',
  FAILED: 'bg-red-100 text-red-700',
  WAITING_FOR_HUMAN: 'bg-amber-100 text-amber-800',
  RESUMING: 'bg-amber-100 text-amber-800',
  RUNNER_LOST: 'bg-red-100 text-red-700',
  SYSTEM_ERROR: 'bg-red-100 text-red-700',
}

export default function StatusBadge({ status }) {
  return (
    <span className={`px-2 py-0.5 rounded-full text-xs ${STYLES[status] || 'bg-gray-100 text-gray-600'}`}>
      {status}
    </span>
  )
}
