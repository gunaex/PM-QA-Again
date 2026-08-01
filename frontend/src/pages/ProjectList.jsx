import { useEffect, useState } from 'react'
import { useNavigate, NavLink } from 'react-router-dom'
import { listProjects, createProject, archiveProject, deleteProject } from '../api/client'
import UserBadge from '../components/UserBadge.jsx'
import PasswordConfirmModal from '../components/PasswordConfirmModal.jsx'
import { useAuth } from '../auth/AuthContext.jsx'

export default function ProjectList() {
  const { user } = useAuth()
  const isAdmin = user?.role === 'ADMIN'
  const canCreate = user?.role === 'ADMIN' || user?.role === 'TESTER'
  const [projects, setProjects] = useState([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(null)
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState('')
  const [externalUrl, setExternalUrl] = useState('')
  const [showArchived, setShowArchived] = useState(false)
  const [confirmAction, setConfirmAction] = useState(null) // { type: 'archive'|'unarchive'|'delete', slug, name }
  const navigate = useNavigate()

  const load = () => {
    setLoading(true)
    setLoadError(null)
    listProjects(showArchived)
      .then(setProjects)
      .catch(() => setLoadError('Could not reach the backend. Your projects are safe — this is a connection problem, not data loss.'))
      .finally(() => setLoading(false))
  }

  useEffect(load, [showArchived])

  const runConfirmedAction = async (password) => {
    const { type, slug } = confirmAction
    if (type === 'delete') {
      await deleteProject(slug, password)
    } else {
      await archiveProject(slug, type === 'archive', password)
    }
    setConfirmAction(null)
    load()
  }

  const handleCreate = async (e) => {
    e.preventDefault()
    if (!name.trim()) return
    setCreating(true)
    try {
      const project = await createProject(name.trim(), externalUrl.trim() || null)
      setName('')
      setExternalUrl('')
      setProjects((prev) => [project, ...prev])
      navigate(`/${project.slug}/dashboard`)
    } finally {
      setCreating(false)
    }
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-5xl mx-auto px-4 sm:px-6 py-10">
        <div className="flex items-center justify-between mb-6 gap-4">
          <h1 className="text-2xl font-semibold text-gray-900">Projects</h1>
          <div className="flex items-center gap-4">
            {isAdmin && (
              <label className="flex items-center gap-1.5 text-sm text-gray-600">
                <input type="checkbox" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} />
                Show archived
              </label>
            )}
            {isAdmin && (
              <NavLink to="/runners" className="text-sm text-gray-500 hover:text-gray-800">
                Runners
              </NavLink>
            )}
            <UserBadge />
          </div>
        </div>

        {canCreate && (
          <form onSubmit={handleCreate} className="flex flex-col sm:flex-row gap-2 mb-8">
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="New QA project name"
              className="flex-1 px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
            />
            <input
              value={externalUrl}
              onChange={(e) => setExternalUrl(e.target.value)}
              placeholder="Linked PM-Again URL (optional)"
              className="flex-1 px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
            />
            <button
              type="submit"
              disabled={creating}
              className="px-4 py-2 bg-emerald-600 text-white text-sm font-medium rounded-md hover:bg-emerald-700 disabled:opacity-50"
            >
              {creating ? 'Creating…' : 'New Project'}
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
        ) : projects.length === 0 ? (
          <p className="text-gray-500 text-sm">No projects yet. Create one above.</p>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {projects.map((p) => (
              <button
                key={p.id}
                onClick={() => navigate(`/${p.slug}/dashboard`)}
                className={`text-left p-5 bg-white border rounded-lg hover:shadow-md hover:border-emerald-300 transition ${
                  p.archived ? 'border-gray-200 opacity-60' : 'border-gray-200'
                }`}
              >
                <div className="flex items-center gap-2 flex-wrap">
                  <h2 className="font-medium text-gray-900">{p.name}</h2>
                  {p.archived && (
                    <span className="px-1.5 py-0.5 text-[10px] uppercase tracking-wide rounded bg-amber-50 text-amber-600">
                      Archived
                    </span>
                  )}
                </div>
                <p className="text-xs text-gray-500 mt-1">{p.slug}</p>
                <p className="text-xs text-gray-400 mt-1">Created {new Date(p.created_at).toLocaleDateString()}</p>
                {isAdmin && (
                  <div className="flex gap-3 mt-3 pt-3 border-t border-gray-100">
                    <span
                      onClick={(e) => {
                        e.stopPropagation()
                        setConfirmAction({ type: p.archived ? 'unarchive' : 'archive', slug: p.slug, name: p.name })
                      }}
                      className="text-xs text-gray-500 hover:underline"
                    >
                      {p.archived ? 'Unarchive' : 'Archive'}
                    </span>
                    <span
                      onClick={(e) => {
                        e.stopPropagation()
                        setConfirmAction({ type: 'delete', slug: p.slug, name: p.name })
                      }}
                      className="text-xs text-red-500 hover:underline"
                    >
                      Delete
                    </span>
                  </div>
                )}
              </button>
            ))}
          </div>
        )}
      </div>

      {confirmAction && (
        <PasswordConfirmModal
          title={
            confirmAction.type === 'delete'
              ? `Delete "${confirmAction.name}"?`
              : confirmAction.type === 'archive'
                ? `Archive "${confirmAction.name}"?`
                : `Unarchive "${confirmAction.name}"?`
          }
          message={
            confirmAction.type === 'delete'
              ? 'This permanently deletes the project and all its data. This cannot be undone. Enter your password to confirm.'
              : confirmAction.type === 'archive'
                ? 'Archived projects are hidden from the project list but not deleted. Enter your password to confirm.'
                : 'This project will reappear in the default project list. Enter your password to confirm.'
          }
          confirmLabel={confirmAction.type === 'delete' ? 'Delete' : confirmAction.type === 'archive' ? 'Archive' : 'Unarchive'}
          danger={confirmAction.type === 'delete'}
          onConfirm={runConfirmedAction}
          onCancel={() => setConfirmAction(null)}
        />
      )}
    </div>
  )
}
