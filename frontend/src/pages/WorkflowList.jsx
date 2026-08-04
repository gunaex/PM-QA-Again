import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Bot, Plus, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { listWorkflows, createWorkflow, deleteWorkflow } from '../api/client'
import { useAuth } from '../auth/AuthContext.jsx'
import ConfirmDialog from '../components/ConfirmDialog.jsx'
import EmptyState from '../components/EmptyState.jsx'
import { CardSkeleton } from '../components/PageSkeleton.jsx'

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
  const [deletingId, setDeletingId] = useState(null)
  const [confirmDelete, setConfirmDelete] = useState(null) // { workflow } or null

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
      toast.success(`Automated test "${workflow.name}" created`)
      navigate(`/${slug}/workflows/${workflow.id}`)
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Failed to create automated test')
    } finally {
      setCreating(false)
    }
  }

  const handleDelete = async () => {
    const workflow = confirmDelete
    if (!workflow) return
    setDeletingId(workflow.id)
    setLoadError(null)
    try {
      await deleteWorkflow(slug, workflow.id)
      setWorkflows((current) => current.filter((item) => item.id !== workflow.id))
      toast.success(`"${workflow.name}" deleted`)
      setConfirmDelete(null)
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Could not delete this automated test.')
    } finally {
      setDeletingId(null)
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <div className="flex items-center gap-3">
          <Bot size={22} className="text-emerald-600" />
          <h2 className="text-xl font-semibold text-gray-900">Automated Tests</h2>
        </div>
        <p className="text-sm text-gray-500 mt-1 ml-9">Record a browser journey, then replay it whenever you need confidence.</p>
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
            className="px-4 py-2 bg-emerald-600 text-white text-sm font-medium rounded-md hover:bg-emerald-700 disabled:opacity-50 flex items-center gap-1.5"
          >
            <Plus size={16} />
            {creating ? 'Creating…' : 'New Automated Test'}
          </button>
        </form>
      )}

      {loading ? (
        <CardSkeleton count={3} />
      ) : loadError ? (
        <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded-md px-4 py-3">
          <p>{loadError}</p>
          <button onClick={load} className="mt-2 text-red-800 font-medium hover:underline">Retry</button>
        </div>
      ) : workflows.length === 0 ? (
        <EmptyState
          icon={Bot}
          title="No automated tests yet"
          description="Give your first test a name, then record the browser journey."
        />
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5 gap-4">
          {workflows.map((workflow) => (
            <div key={workflow.id} className="relative bg-white border border-gray-200 rounded-xl hover:shadow-md hover:border-emerald-300 transition">
              <button
                onClick={() => navigate(`/${slug}/workflows/${workflow.id}`)}
                className="w-full h-full text-left p-5 pr-16 rounded-xl"
              >
                <h3 className="font-medium text-gray-900">{workflow.name}</h3>
                {workflow.description && <p className="text-xs text-gray-500 mt-1">{workflow.description}</p>}
                <p className="text-xs text-gray-400 mt-3">
                  {workflow.published_revision_label ? 'Ready to run' : 'Ready to record'}
                </p>
              </button>
              {canEdit && (
                <button
                  onClick={() => setConfirmDelete(workflow)}
                  disabled={deletingId === workflow.id}
                  className="absolute top-3 right-3 p-1.5 text-red-500 hover:bg-red-50 rounded-md transition"
                  title="Delete"
                >
                  <Trash2 size={16} />
                </button>
              )}
            </div>
          ))}
        </div>
      )}

      <ConfirmDialog
        open={!!confirmDelete}
        onClose={() => setConfirmDelete(null)}
        onConfirm={handleDelete}
        title={`Delete "${confirmDelete?.name}"?`}
        message="Existing run history is kept, but this automated test will be removed."
        confirmLabel="Delete"
        danger
        loading={!!deletingId}
      />
    </div>
  )
}
