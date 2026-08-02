import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { listSuites, listRevisions, listCycles, createQuickTest, runSuiteNow, rerunCycle } from '../api/client'

const OPTIONS = [
  { key: 'quick', label: 'Quick Manual Test', description: 'One title, straight to an active execution screen.' },
  { key: 'suite', label: 'Run Existing Suite', description: 'Create a new cycle from a published suite revision.' },
  { key: 'rerun', label: 'Rerun Previous Cycle', description: 'Rerun an entire cycle, or just its FAIL/BLOCKED cases.' },
]

/** Dashboard → Start Testing → active Cycle Execution, in as few clicks
 * as possible. Reuses the exact existing TestSuite/ScriptRevision/
 * TestCase/TestCycle/CycleTestResult models via the backend's
 * quick-test/run-now/rerun endpoints — no parallel testing model. */
export default function StartTestingModal({ slug, onClose }) {
  const navigate = useNavigate()
  const [mode, setMode] = useState(null) // null | 'quick' | 'suite' | 'rerun'
  const [error, setError] = useState(null)
  const [submitting, setSubmitting] = useState(false)

  // Quick Manual Test
  const [title, setTitle] = useState('')
  const [expectedResult, setExpectedResult] = useState('')
  const [requireEvidence, setRequireEvidence] = useState(true)

  // Run Existing Suite
  const [suites, setSuites] = useState([])
  const [suiteId, setSuiteId] = useState('')

  // Rerun Previous Cycle
  const [cycles, setCycles] = useState([])
  const [rerunCycleId, setRerunCycleId] = useState('')
  const [rerunMode, setRerunMode] = useState('all')

  useEffect(() => {
    if (mode === 'suite') listSuites(slug).then(setSuites)
    if (mode === 'rerun') listCycles(slug).then(setCycles)
  }, [slug, mode])

  const goToExecution = (cycleId, resultId) => {
    onClose()
    navigate(`/${slug}/cycles/${cycleId}${resultId ? `?resultId=${resultId}` : ''}`)
  }

  const handleQuickTest = async (e) => {
    e.preventDefault()
    if (!title.trim()) return
    setSubmitting(true)
    setError(null)
    try {
      const { cycle, result_id } = await createQuickTest(slug, {
        title: title.trim(),
        expected_result_md: expectedResult.trim() || undefined,
        require_evidence_for_pass: requireEvidence,
      })
      goToExecution(cycle.id, result_id)
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not start this test')
    } finally {
      setSubmitting(false)
    }
  }

  const handleRunSuite = async () => {
    if (!suiteId) return
    setSubmitting(true)
    setError(null)
    try {
      const revisions = await listRevisions(slug, suiteId)
      const published = revisions.find((r) => r.status === 'PUBLISHED')
      if (!published) {
        setError('This suite has no published revision yet.')
        return
      }
      const cycle = await runSuiteNow(slug, suiteId, published.id)
      goToExecution(cycle.id)
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not run this suite')
    } finally {
      setSubmitting(false)
    }
  }

  const handleRerun = async () => {
    if (!rerunCycleId) return
    setSubmitting(true)
    setError(null)
    try {
      const cycle = await rerunCycle(slug, rerunCycleId, rerunMode)
      goToExecution(cycle.id)
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not rerun this cycle')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div className="bg-white rounded-lg shadow-xl w-full max-w-md p-5 space-y-4" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between">
          <h3 className="text-lg font-semibold text-gray-900">Start Testing</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            ✕
          </button>
        </div>

        {!mode && (
          <div className="space-y-2">
            {OPTIONS.map((o) => (
              <button
                key={o.key}
                autoFocus={o.key === 'quick'}
                onClick={() => setMode(o.key)}
                className="w-full text-left p-3 border border-gray-200 rounded-md hover:border-emerald-400 hover:bg-emerald-50"
              >
                <p className="text-sm font-medium text-gray-900">{o.label}</p>
                <p className="text-xs text-gray-500">{o.description}</p>
              </button>
            ))}
          </div>
        )}

        {mode === 'quick' && (
          <form onSubmit={handleQuickTest} className="space-y-3">
            <div>
              <label className="block text-xs font-medium text-gray-500 mb-1">Test title *</label>
              <input
                autoFocus
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="e.g. Login works with valid credentials"
                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-500 mb-1">Expected result (optional)</label>
              <textarea
                value={expectedResult}
                onChange={(e) => setExpectedResult(e.target.value)}
                rows={2}
                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
              />
            </div>
            <label className="flex items-center gap-2 text-xs text-gray-600">
              <input type="checkbox" checked={requireEvidence} onChange={(e) => setRequireEvidence(e.target.checked)} />
              Evidence required for PASS
            </label>
            {error && <p className="text-xs text-red-600">{error}</p>}
            <div className="flex gap-2">
              <button type="button" onClick={() => setMode(null)} className="px-3 py-2 text-sm border border-gray-300 rounded-md hover:bg-gray-50">
                Back
              </button>
              <button
                type="submit"
                disabled={submitting || !title.trim()}
                className="flex-1 px-4 py-2 bg-emerald-600 text-white text-sm font-medium rounded-md hover:bg-emerald-700 disabled:opacity-50"
              >
                {submitting ? 'Starting…' : 'Start Test'}
              </button>
            </div>
          </form>
        )}

        {mode === 'suite' && (
          <div className="space-y-3">
            <label className="block text-xs font-medium text-gray-500">Suite</label>
            <select
              value={suiteId}
              onChange={(e) => setSuiteId(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
            >
              <option value="">Select a suite…</option>
              {suites.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
            {error && <p className="text-xs text-red-600">{error}</p>}
            <div className="flex gap-2">
              <button onClick={() => setMode(null)} className="px-3 py-2 text-sm border border-gray-300 rounded-md hover:bg-gray-50">
                Back
              </button>
              <button
                onClick={handleRunSuite}
                disabled={submitting || !suiteId}
                className="flex-1 px-4 py-2 bg-emerald-600 text-white text-sm font-medium rounded-md hover:bg-emerald-700 disabled:opacity-50"
              >
                {submitting ? 'Starting…' : 'Run Now'}
              </button>
            </div>
          </div>
        )}

        {mode === 'rerun' && (
          <div className="space-y-3">
            <label className="block text-xs font-medium text-gray-500">Cycle</label>
            <select
              value={rerunCycleId}
              onChange={(e) => setRerunCycleId(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
            >
              <option value="">Select a cycle…</option>
              {cycles.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
            <label className="block text-xs font-medium text-gray-500">Rerun</label>
            <select
              value={rerunMode}
              onChange={(e) => setRerunMode(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
            >
              <option value="all">Entire cycle</option>
              <option value="fail_blocked">FAIL and BLOCKED cases only</option>
            </select>
            {error && <p className="text-xs text-red-600">{error}</p>}
            <div className="flex gap-2">
              <button onClick={() => setMode(null)} className="px-3 py-2 text-sm border border-gray-300 rounded-md hover:bg-gray-50">
                Back
              </button>
              <button
                onClick={handleRerun}
                disabled={submitting || !rerunCycleId}
                className="flex-1 px-4 py-2 bg-emerald-600 text-white text-sm font-medium rounded-md hover:bg-emerald-700 disabled:opacity-50"
              >
                {submitting ? 'Starting…' : 'Rerun'}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
