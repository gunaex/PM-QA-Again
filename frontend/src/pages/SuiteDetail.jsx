import { useEffect, useState } from 'react'
import { NavLink, useNavigate, useParams } from 'react-router-dom'
import { getSuite, listRevisions, createRevision, runSuiteNow } from '../api/client'
import { useAuth } from '../auth/AuthContext.jsx'
import StatusBadge from '../components/StatusBadge.jsx'

export default function SuiteDetail() {
  const { slug, suiteId } = useParams()
  const { user } = useAuth()
  const canEdit = user?.role === 'ADMIN' || user?.role === 'TESTER'
  const navigate = useNavigate()

  const [suite, setSuite] = useState(null)
  const [revisions, setRevisions] = useState([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(null)
  const [label, setLabel] = useState('')
  const [summary, setSummary] = useState('')
  const [creating, setCreating] = useState(false)
  const [runningNow, setRunningNow] = useState(null)

  const load = () => {
    setLoading(true)
    setLoadError(null)
    Promise.all([getSuite(slug, suiteId), listRevisions(slug, suiteId)])
      .then(([s, revs]) => {
        setSuite(s)
        setRevisions(revs)
      })
      .catch(() => setLoadError('Could not reach the backend.'))
      .finally(() => setLoading(false))
  }

  useEffect(load, [slug, suiteId])

  const handleCreate = async (e) => {
    e.preventDefault()
    if (!label.trim()) return
    setCreating(true)
    try {
      const revision = await createRevision(slug, suiteId, { revision_label: label.trim(), change_summary: summary || null })
      setLabel('')
      setSummary('')
      navigate(`/${slug}/suites/${suiteId}/revisions/${revision.id}`)
    } catch (err) {
      setLoadError(err.response?.data?.detail || 'Could not create revision')
    } finally {
      setCreating(false)
    }
  }

  const handleRunNow = async (revisionId) => {
    setRunningNow(revisionId)
    setLoadError(null)
    try {
      const cycle = await runSuiteNow(slug, suiteId, revisionId)
      navigate(`/${slug}/cycles/${cycle.id}`)
    } catch (err) {
      setLoadError(err.response?.data?.detail || 'Could not run this suite')
    } finally {
      setRunningNow(null)
    }
  }

  if (loading) return <p className="text-gray-500 text-sm">Loading…</p>
  if (loadError && !suite)
    return (
      <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded-md px-4 py-3">
        <p>{loadError}</p>
        <button onClick={load} className="mt-2 text-red-800 font-medium hover:underline">
          Retry
        </button>
      </div>
    )

  return (
    <div className="space-y-6">
      <div>
        <NavLink to={`/${slug}/suites`} className="text-sm text-gray-500 hover:text-gray-800">
          &larr; Test Suites
        </NavLink>
        <div className="flex items-center gap-2 flex-wrap mt-1">
          <h2 className="text-xl font-semibold text-gray-900">{suite.name}</h2>
          <StatusBadge status={suite.status} />
          <span className="px-1.5 py-0.5 text-[10px] uppercase tracking-wide rounded bg-gray-100 text-gray-500">
            {suite.suite_type}
          </span>
        </div>
      </div>

      {canEdit && (
        <form onSubmit={handleCreate} className="flex flex-col sm:flex-row gap-2">
          <input
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="Revision label (e.g. v1, 2026-08-01)"
            className="flex-1 px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
          />
          <input
            value={summary}
            onChange={(e) => setSummary(e.target.value)}
            placeholder="Change summary (optional)"
            className="flex-1 px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
          />
          <button
            type="submit"
            disabled={creating}
            className="px-4 py-2 bg-emerald-600 text-white text-sm font-medium rounded-md hover:bg-emerald-700 disabled:opacity-50"
          >
            {creating ? 'Creating…' : 'New Draft Revision'}
          </button>
        </form>
      )}
      {loadError && <p className="text-xs text-red-600">{loadError}</p>}

      {revisions.length === 0 ? (
        <p className="text-gray-500 text-sm">No revisions yet. Create a draft above.</p>
      ) : (
        <div className="bg-white border border-gray-200 rounded-lg divide-y divide-gray-100">
          {revisions.map((r) => (
            <div key={r.id} className="w-full flex items-center justify-between gap-4 px-5 py-3 hover:bg-gray-50">
              <button onClick={() => navigate(`/${slug}/suites/${suiteId}/revisions/${r.id}`)} className="text-left flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-gray-900">{r.revision_label}</span>
                  <StatusBadge status={r.status} />
                </div>
                {r.change_summary && <p className="text-xs text-gray-500 mt-0.5">{r.change_summary}</p>}
              </button>
              <span className="text-xs text-gray-400 shrink-0">{new Date(r.created_at).toLocaleDateString()}</span>
              {canEdit && r.status === 'PUBLISHED' && (
                <button
                  onClick={() => handleRunNow(r.id)}
                  disabled={runningNow === r.id}
                  className="shrink-0 px-3 py-1.5 text-xs bg-emerald-600 text-white rounded-md hover:bg-emerald-700 disabled:opacity-50"
                >
                  {runningNow === r.id ? 'Starting…' : 'Run now'}
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
