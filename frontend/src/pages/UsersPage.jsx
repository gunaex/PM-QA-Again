import { useEffect, useState } from 'react'
import { NavLink } from 'react-router-dom'
import {
  listUsers,
  createUser,
  setUserActive,
  listUserProjects,
  addUserProject,
  removeUserProject,
  listProjects,
} from '../api/client'
import UserBadge from '../components/UserBadge.jsx'
import { useAuth } from '../auth/AuthContext.jsx'

const ROLE_COLOR = {
  ADMIN: 'bg-purple-100 text-purple-700',
  TESTER: 'bg-blue-100 text-blue-700',
  VIEWER: 'bg-gray-100 text-gray-600',
}

/** ADMIN-only user management -- create TESTER/VIEWER accounts and
 * assign which projects each can access (ADR-0003). ADMIN always
 * reaches every project and has no membership rows of its own. */
export default function UsersPage() {
  const { user: me } = useAuth()
  const isAdmin = me?.role === 'ADMIN'

  const [users, setUsers] = useState([])
  const [allProjects, setAllProjects] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState('TESTER')
  const [creating, setCreating] = useState(false)
  const [createdInfo, setCreatedInfo] = useState(null)

  const [expandedUserId, setExpandedUserId] = useState(null)
  const [memberships, setMemberships] = useState({}) // userId -> ProjectMembershipOut[]
  const [membershipBusy, setMembershipBusy] = useState(null) // `${userId}:${projectId}` while a toggle is in flight

  const load = () => {
    setLoading(true)
    Promise.all([listUsers(), listProjects(true)])
      .then(([u, p]) => {
        setUsers(u)
        setAllProjects(p)
      })
      .catch(() => setError('Could not reach the backend.'))
      .finally(() => setLoading(false))
  }

  useEffect(load, [])

  const handleCreate = async (e) => {
    e.preventDefault()
    if (!email.trim() || !password.trim()) return
    setCreating(true)
    setError(null)
    try {
      const created = await createUser(email.trim(), password, role)
      setCreatedInfo(created)
      setEmail('')
      setPassword('')
      setRole('TESTER')
      load()
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not create this user')
    } finally {
      setCreating(false)
    }
  }

  const handleToggleActive = async (u) => {
    await setUserActive(u.id, !u.active)
    load()
  }

  const toggleExpand = async (u) => {
    if (expandedUserId === u.id) {
      setExpandedUserId(null)
      return
    }
    setExpandedUserId(u.id)
    if (!memberships[u.id]) {
      const rows = await listUserProjects(u.id)
      setMemberships((prev) => ({ ...prev, [u.id]: rows }))
    }
  }

  const isMember = (userId, projectId) => (memberships[userId] || []).some((m) => m.project_id === projectId)

  const handleToggleProject = async (userId, project) => {
    const key = `${userId}:${project.id}`
    setMembershipBusy(key)
    try {
      if (isMember(userId, project.id)) {
        await removeUserProject(userId, project.id)
      } else {
        await addUserProject(userId, project.id)
      }
      const rows = await listUserProjects(userId)
      setMemberships((prev) => ({ ...prev, [userId]: rows }))
    } finally {
      setMembershipBusy(null)
    }
  }

  if (!isAdmin) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <p className="text-sm text-gray-500">User management is ADMIN-only.</p>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-4xl mx-auto px-4 sm:px-6 py-10">
        <div className="flex items-center justify-between mb-6 gap-4">
          <div>
            <NavLink to="/" className="text-sm text-gray-500 hover:text-gray-800">
              &larr; Projects
            </NavLink>
            <h1 className="text-2xl font-semibold text-gray-900 mt-1">Users</h1>
          </div>
          <UserBadge />
        </div>

        {createdInfo && (
          <div className="mb-6 p-4 bg-amber-50 border border-amber-300 rounded-lg">
            <p className="text-sm font-medium text-amber-900">
              Account created for {createdInfo.email} ({createdInfo.role}) — they must set a new password on first
              login.
            </p>
            {createdInfo.role !== 'ADMIN' && (
              <p className="text-xs text-amber-700 mt-1">
                They have no project access yet — expand their row below to assign one.
              </p>
            )}
            <button onClick={() => setCreatedInfo(null)} className="mt-2 text-xs text-amber-800 hover:underline">
              Dismiss
            </button>
          </div>
        )}

        <form onSubmit={handleCreate} className="bg-white border border-gray-200 rounded-lg p-4 mb-6 flex flex-wrap gap-2 items-end">
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Email</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="new.user@company.com"
              className="px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Temporary password</label>
            <input
              type="text"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="TempPass123!"
              className="px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Role</label>
            <select
              value={role}
              onChange={(e) => setRole(e.target.value)}
              className="px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
            >
              <option value="TESTER">TESTER</option>
              <option value="VIEWER">VIEWER</option>
              <option value="ADMIN">ADMIN</option>
            </select>
          </div>
          <button
            type="submit"
            disabled={creating || !email.trim() || !password.trim()}
            className="px-4 py-2 bg-emerald-600 text-white text-sm font-medium rounded-md hover:bg-emerald-700 disabled:opacity-50"
          >
            {creating ? 'Creating…' : 'Create User'}
          </button>
        </form>

        {error && <p className="text-sm text-red-600 mb-4">{error}</p>}

        {loading ? (
          <p className="text-sm text-gray-500">Loading…</p>
        ) : users.length === 0 ? (
          <p className="text-sm text-gray-500">No users yet.</p>
        ) : (
          <div className="bg-white border border-gray-200 rounded-lg divide-y divide-gray-100">
            {users.map((u) => (
              <div key={u.id}>
                <div className="flex items-center justify-between gap-3 px-4 py-3">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-gray-900 text-sm">{u.email}</span>
                    <span className={`px-2 py-0.5 rounded-full text-xs ${ROLE_COLOR[u.role] || 'bg-gray-100 text-gray-600'}`}>
                      {u.role}
                    </span>
                    {!u.active && <span className="px-2 py-0.5 rounded-full text-xs bg-red-100 text-red-700">Inactive</span>}
                    {u.must_change_password && (
                      <span className="px-2 py-0.5 rounded-full text-xs bg-amber-100 text-amber-700">Password change pending</span>
                    )}
                  </div>
                  <div className="flex items-center gap-3 shrink-0">
                    {u.role === 'ADMIN' ? (
                      <span className="text-xs text-gray-400">All projects</span>
                    ) : (
                      <button onClick={() => toggleExpand(u)} className="text-xs text-emerald-600 hover:underline">
                        {expandedUserId === u.id ? 'Hide projects' : 'Manage projects'}
                      </button>
                    )}
                    {u.id !== me.id && (
                      <button onClick={() => handleToggleActive(u)} className="text-xs text-gray-500 hover:underline">
                        {u.active ? 'Deactivate' : 'Reactivate'}
                      </button>
                    )}
                  </div>
                </div>

                {expandedUserId === u.id && u.role !== 'ADMIN' && (
                  <div className="px-4 pb-3 pt-1 bg-gray-50 border-t border-gray-100">
                    <p className="text-xs font-medium text-gray-500 uppercase mb-2">Project access</p>
                    {allProjects.length === 0 ? (
                      <p className="text-xs text-gray-400">No projects exist yet.</p>
                    ) : (
                      <div className="flex flex-wrap gap-2">
                        {allProjects.map((p) => {
                          const member = isMember(u.id, p.id)
                          const busy = membershipBusy === `${u.id}:${p.id}`
                          return (
                            <button
                              key={p.id}
                              onClick={() => handleToggleProject(u.id, p)}
                              disabled={busy}
                              className={`px-2.5 py-1 rounded-full text-xs border disabled:opacity-50 ${
                                member
                                  ? 'bg-emerald-100 text-emerald-700 border-emerald-300'
                                  : 'bg-white text-gray-500 border-gray-300 hover:bg-gray-100'
                              }`}
                            >
                              {member ? '✓ ' : ''}
                              {p.name}
                            </button>
                          )
                        })}
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
