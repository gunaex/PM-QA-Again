import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { listCycles, createCycle, listSuites, listRevisions } from '../api/client'
import { useAuth } from '../auth/AuthContext.jsx'
import StatusBadge from '../components/StatusBadge.jsx'

const ENVIRONMENTS = ['NON-PROD', 'PROD', 'UAT', 'STR', 'Other']

export default function CycleList() {
  const { slug } = useParams()
  const { user } = useAuth()
  const canEdit = user?.role === 'ADMIN' || user?.role === 'TESTER'
  const navigate = useNavigate()

  const [cycles, setCycles] = useState([])
  const [suites, setSuites] = useState([])
  const [revisions, setRevisions] = useState([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(null)
  const [creating, setCreating] = useState(false)
  const [form, setForm] = useState({ suite_id: '', script_revision_id: '', name: '', environment: '', target_base_url: '' })
  // 'Other' shows a free-text input below the dropdown; any fixed choice
  // writes straight into form.environment (the value actually submitted).
  const [environmentChoice, setEnvironmentChoice] = useState('')

  const load = () => {
    setLoading(true)
    setLoadError(null)
    Promise.all([listCycles(slug), listSuites(slug)])
      .then(([c, s]) => {
        setCycles(c)
        setSuites(s)
      })
      .catch(() => setLoadError('Could not reach the backend.'))
      .finally(() => setLoading(false))
  }

  useEffect(load, [slug])

  const onSuiteChange = async (suiteId) => {
    setForm((f) => ({ ...f, suite_id: suiteId, script_revision_id: '' }))
    if (!suiteId) {
      setRevisions([])
      return
    }
    const revs = await listRevisions(slug, suiteId)
    setRevisions(revs.filter((r) => r.status === 'PUBLISHED'))
  }

  const handleCreate = async (e) => {
    e.preventDefault()
    if (!form.suite_id || !form.script_revision_id || !form.name.trim() || !form.environment.trim()) return
    setCreating(true)
    setLoadError(null)
    try {
      const cycle = await createCycle(slug, {
        suite_id: Number(form.suite_id),
        script_revision_id: Number(form.script_revision_id),
        name: form.name.trim(),
        environment: form.environment.trim(),
        target_base_url: form.target_base_url.trim() || null,
      })
      navigate(`/${slug}/cycles/${cycle.id}`)
    } catch (err) {
      setLoadError(err.response?.data?.detail || 'Could not create cycle')
    } finally {
      setCreating(false)
    }
  }

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-semibold text-gray-900">Test Cycles</h2>

      {canEdit && (
        <form onSubmit={handleCreate} className="bg-white border border-gray-200 rounded-lg p-5 space-y-3">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <select
              required
              value={form.suite_id}
              onChange={(e) => onSuiteChange(e.target.value)}
              className="px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
            >
              <option value="">Select suite…</option>
              {suites.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
            <select
              required
              value={form.script_revision_id}
              onChange={(e) => setForm({ ...form, script_revision_id: e.target.value })}
              disabled={!form.suite_id}
              className="px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500 disabled:opacity-50"
            >
              <option value="">Select published revision…</option>
              {revisions.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.revision_label}
                </option>
              ))}
            </select>
          </div>
          {form.suite_id && revisions.length === 0 && (
            <p className="text-xs text-amber-600">This suite has no PUBLISHED revision yet.</p>
          )}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <input
              required
              placeholder="Cycle name (e.g. Pre-golive smoke)"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              className="px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
            />
            <div>
              <select
                required
                value={environmentChoice}
                onChange={(e) => {
                  const choice = e.target.value
                  setEnvironmentChoice(choice)
                  setForm({ ...form, environment: choice === 'Other' ? '' : choice })
                }}
                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
              >
                <option value="">Select environment…</option>
                {ENVIRONMENTS.map((env) => (
                  <option key={env} value={env}>
                    {env}
                  </option>
                ))}
              </select>
              {environmentChoice === 'Other' && (
                <input
                  required
                  autoFocus
                  placeholder="Environment name"
                  value={form.environment}
                  onChange={(e) => setForm({ ...form, environment: e.target.value })}
                  className="w-full mt-2 px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
                />
              )}
            </div>
            <input
              placeholder="Target URL (optional)"
              value={form.target_base_url}
              onChange={(e) => setForm({ ...form, target_base_url: e.target.value })}
              className="px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
            />
          </div>
          <button
            type="submit"
            disabled={creating}
            className="px-4 py-2 bg-emerald-600 text-white text-sm font-medium rounded-md hover:bg-emerald-700 disabled:opacity-50"
          >
            {creating ? 'Creating…' : 'New Cycle'}
          </button>
        </form>
      )}
      {loadError && <p className="text-xs text-red-600">{loadError}</p>}

      {loading ? (
        <p className="text-gray-500 text-sm">Loading…</p>
      ) : cycles.length === 0 ? (
        <p className="text-gray-500 text-sm">No test cycles yet.</p>
      ) : (
        <div className="bg-white border border-gray-200 rounded-lg divide-y divide-gray-100">
          {cycles.map((c) => (
            <button
              key={c.id}
              onClick={() => navigate(`/${slug}/cycles/${c.id}`)}
              className="w-full flex items-center justify-between gap-4 px-5 py-3 text-left hover:bg-gray-50"
            >
              <div>
                <div className="flex items-center gap-2">
                  <span className="font-medium text-gray-900">{c.name}</span>
                  <StatusBadge status={c.status} />
                </div>
                <p className="text-xs text-gray-500 mt-0.5">{c.environment}</p>
              </div>
              {c.result_counts && (
                <div className="text-xs text-gray-500 shrink-0">
                  {c.result_counts.PASS} pass · {c.result_counts.FAIL} fail · {c.result_counts.BLOCKED} blocked ·{' '}
                  {c.result_counts.NOT_APPLICABLE} n/a · {c.result_counts.NOT_RUN} not run
                </div>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
