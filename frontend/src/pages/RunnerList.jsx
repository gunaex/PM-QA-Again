import { useEffect, useState } from 'react'
import { NavLink } from 'react-router-dom'
import { listRunnerTokens, createRunnerToken, revokeRunnerToken } from '../api/client'
import UserBadge from '../components/UserBadge.jsx'
import { useAuth } from '../auth/AuthContext.jsx'

const STATUS_COLOR = {
  ONLINE: 'bg-green-100 text-green-700',
  STALE: 'bg-amber-100 text-amber-700',
  OFFLINE: 'bg-gray-100 text-gray-500',
  REVOKED: 'bg-red-100 text-red-700',
}

export default function RunnerList() {
  const { user } = useAuth()
  const isAdmin = user?.role === 'ADMIN'
  const [runners, setRunners] = useState([])
  const [loading, setLoading] = useState(true)
  const [label, setLabel] = useState('')
  const [newToken, setNewToken] = useState(null)

  const load = () => {
    setLoading(true)
    listRunnerTokens()
      .then(setRunners)
      .finally(() => setLoading(false))
  }

  useEffect(load, [])
  useEffect(() => {
    const interval = setInterval(load, 5000)
    return () => clearInterval(interval)
  }, [])

  const handleCreate = async (e) => {
    e.preventDefault()
    if (!label.trim()) return
    const result = await createRunnerToken(label.trim())
    setNewToken(result)
    setLabel('')
    load()
  }

  const handleRevoke = async (id) => {
    if (!window.confirm('Revoke this runner token? The runner process will be rejected on its next call.')) return
    await revokeRunnerToken(id)
    load()
  }

  if (!isAdmin) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <p className="text-sm text-gray-500">Runner management is ADMIN-only.</p>
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
            <h1 className="text-2xl font-semibold text-gray-900 mt-1">Runners</h1>
          </div>
          <UserBadge />
        </div>

        {newToken && (
          <div className="mb-6 p-4 bg-amber-50 border border-amber-300 rounded-lg">
            <p className="text-sm font-medium text-amber-900">
              Runner token created — copy it now, it will never be shown again:
            </p>
            <code className="block mt-2 p-2 bg-white border border-amber-200 rounded text-xs break-all">{newToken.token}</code>
            <p className="text-xs text-amber-700 mt-2">Set this as RUNNER_TOKEN in the runner process's environment (never in a tracked file).</p>
            <button onClick={() => setNewToken(null)} className="mt-2 text-xs text-amber-800 hover:underline">
              Dismiss
            </button>
          </div>
        )}

        <form onSubmit={handleCreate} className="flex gap-2 mb-6">
          <input
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="New runner label (e.g. laptop-1)"
            className="flex-1 px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
          />
          <button type="submit" className="px-4 py-2 bg-emerald-600 text-white text-sm font-medium rounded-md hover:bg-emerald-700">
            Register Runner
          </button>
        </form>

        {loading ? (
          <p className="text-sm text-gray-500">Loading…</p>
        ) : runners.length === 0 ? (
          <p className="text-sm text-gray-500">No runners registered yet.</p>
        ) : (
          <div className="bg-white border border-gray-200 rounded-lg divide-y divide-gray-100">
            {runners.map((r) => (
              <div key={r.id} className="flex items-center justify-between gap-3 px-4 py-3">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-gray-900 text-sm">{r.label}</span>
                    <span className={`px-2 py-0.5 rounded-full text-xs ${STATUS_COLOR[r.status] || STATUS_COLOR.OFFLINE}`}>{r.status}</span>
                  </div>
                  <p className="text-xs text-gray-500 mt-0.5">
                    {r.last_heartbeat_at ? `Last heartbeat: ${new Date(r.last_heartbeat_at).toLocaleString()}` : 'Never contacted the backend'}
                  </p>
                </div>
                {!r.revoked && (
                  <button onClick={() => handleRevoke(r.id)} className="text-xs text-red-600 hover:underline shrink-0">
                    Revoke
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
