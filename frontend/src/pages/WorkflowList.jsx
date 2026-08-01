import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { listWorkflows, createWorkflow } from '../api/client'
import { useAuth } from '../auth/AuthContext.jsx'

export default function WorkflowList() {
  const { slug } = useParams()
  const { user } = useAuth()
  const canEdit = user?.role === 'ADMIN' || user?.role === 'TESTER'
  const navigate = useNavigate()

  const [workflows, setWorkflows] = useState([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(null)
  const [name, setName] = useState('')
  const [creating, setCreating] = useState(false)

  const load = () => {
    setLoading(true)
    setLoadError(null)
    listWorkflows(slug)
      .then(setWorkflows)
      .catch(() => setLoadError('Could not reach the backend.'))
      .finally(() => setLoading(false))
  }

  useEffect(load, [slug])

  const handleCreate = async (e) => {
    e.preventDefault()
    if (!name.trim()) return
    setCreating(true)
    try {
      const wf = await createWorkflow(slug, { name: name.trim() })
      setName('')
      setWorkflows((prev) => [wf, ...prev])
      navigate(`/${slug}/workflows/${wf.id}`)
    } finally {
      setCreating(false)
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold text-gray-900">Workflows</h2>
      </div>
      <p className="text-xs text-gray-500 -mt-4">
        Automated browser flows (HYB-1) — draft/publish/clone just like test suite revisions. Execution (HYB-2)
        and the recorder (HYB-3) are not built yet; this is the workflow editor only.
      </p>

      {canEdit && (
        <form onSubmit={handleCreate} className="flex flex-col sm:flex-row gap-2">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="New workflow name"
            className="flex-1 px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
          />
          <button
            type="submit"
            disabled={creating}
            className="px-4 py-2 bg-emerald-600 text-white text-sm font-medium rounded-md hover:bg-emerald-700 disabled:opacity-50"
          >
            {creating ? 'Creating…' : 'New Workflow'}
          </button>
        </form>
      )}

      {loading ? (
        <p className="text-gray-500 text-sm">Loading…</p>
      ) : loadError ? (
        <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded-md px-4 py-3">
          <p>{loadError}</p>
          <button onClick={load} className="mt-2 text-red-800 font-medium hover:underline">
            Retry
          </button>
        </div>
      ) : workflows.length === 0 ? (
        <p className="text-gray-500 text-sm">No workflows yet. Create one above.</p>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {workflows.map((w) => (
            <button
              key={w.id}
              onClick={() => navigate(`/${slug}/workflows/${w.id}`)}
              className="text-left p-5 bg-white border border-gray-200 rounded-lg hover:shadow-md hover:border-emerald-300 transition"
            >
              <div className="flex items-center gap-2 flex-wrap">
                <h3 className="font-medium text-gray-900">{w.name}</h3>
              </div>
              {w.description && <p className="text-xs text-gray-500 mt-1">{w.description}</p>}
              <p className="text-xs text-gray-400 mt-2">
                {w.published_revision_label ? `Published: ${w.published_revision_label}` : 'No published revision yet'}
              </p>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
