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

  const handleCreate = async (event) => {
    event.preventDefault()
    if (!name.trim()) return
    setCreating(true)
    try {
      const workflow = await createWorkflow(slug, { name: name.trim() })
      navigate(`/${slug}/workflows/${workflow.id}`)
    } finally {
      setCreating(false)
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold text-gray-900">Automated Tests</h2>
        <p className="text-sm text-gray-500 mt-1">Record a browser journey, then replay it whenever you need confidence.</p>
      </div>

      {canEdit && (
        <form onSubmit={handleCreate} className="flex flex-col sm:flex-row gap-2">
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Test name, e.g. Customer can sign in"
            className="flex-1 px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
          />
          <button
            type="submit"
            disabled={creating || !name.trim()}
            className="px-4 py-2 bg-emerald-600 text-white text-sm font-medium rounded-md hover:bg-emerald-700 disabled:opacity-50"
          >
            {creating ? 'Creating…' : 'New Automated Test'}
          </button>
        </form>
      )}

      {loading ? (
        <p className="text-gray-500 text-sm">Loading…</p>
      ) : loadError ? (
        <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded-md px-4 py-3">
          <p>{loadError}</p>
          <button onClick={load} className="mt-2 text-red-800 font-medium hover:underline">Retry</button>
        </div>
      ) : workflows.length === 0 ? (
        <div className="text-center bg-white border border-dashed border-gray-300 rounded-xl px-6 py-12">
          <p className="font-medium text-gray-800">No automated tests yet</p>
          <p className="text-gray-500 text-sm mt-1">Give your first test a name, then record the journey in your browser.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5 gap-4">
          {workflows.map((workflow) => (
            <button
              key={workflow.id}
              onClick={() => navigate(`/${slug}/workflows/${workflow.id}`)}
              className="text-left p-5 bg-white border border-gray-200 rounded-xl hover:shadow-md hover:border-emerald-300 transition"
            >
              <h3 className="font-medium text-gray-900">{workflow.name}</h3>
              {workflow.description && <p className="text-xs text-gray-500 mt-1">{workflow.description}</p>}
              <p className="text-xs text-gray-400 mt-3">
                {workflow.published_revision_label ? 'Ready to run' : 'Ready to record'}
              </p>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
