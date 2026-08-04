import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { BookOpen, Plus } from 'lucide-react'
import { toast } from 'sonner'
import { listSuites, createSuite } from '../api/client'
import { useAuth } from '../auth/AuthContext.jsx'
import StatusBadge from '../components/StatusBadge.jsx'
import EmptyState from '../components/EmptyState.jsx'
import { CardSkeleton } from '../components/PageSkeleton.jsx'

const SUITE_TYPES = ['REGRESSION', 'UAT', 'SMOKE', 'INTEGRATION', 'OTHER']

export default function SuiteList() {
  const { slug } = useParams()
  const { user } = useAuth()
  const canEdit = user?.role === 'ADMIN' || user?.role === 'TESTER'
  const navigate = useNavigate()

  const [suites, setSuites] = useState([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(null)
  const [name, setName] = useState('')
  const [suiteType, setSuiteType] = useState('REGRESSION')
  const [creating, setCreating] = useState(false)

  const load = () => {
    setLoading(true)
    setLoadError(null)
    listSuites(slug)
      .then(setSuites)
      .catch(() => setLoadError('Could not reach the backend.'))
      .finally(() => setLoading(false))
  }

  useEffect(load, [slug])

  const handleCreate = async (e) => {
    e.preventDefault()
    if (!name.trim()) return
    setCreating(true)
    try {
      const suite = await createSuite(slug, { name: name.trim(), suite_type: suiteType })
      setName('')
      setSuites((prev) => [suite, ...prev])
      toast.success(`Suite "${suite.name}" created`)
      navigate(`/${slug}/suites/${suite.id}`)
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Failed to create suite')
    } finally {
      setCreating(false)
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <BookOpen size={22} className="text-emerald-600" />
        <h2 className="text-xl font-semibold text-gray-900">Test Suites</h2>
      </div>

      {canEdit && (
        <form onSubmit={handleCreate} className="flex flex-col sm:flex-row gap-2">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="New suite name"
            className="flex-1 px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
          />
          <select
            value={suiteType}
            onChange={(e) => setSuiteType(e.target.value)}
            className="px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
          >
            {SUITE_TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
          <button
            type="submit"
            disabled={creating}
            className="px-4 py-2 bg-emerald-600 text-white text-sm font-medium rounded-md hover:bg-emerald-700 disabled:opacity-50 flex items-center gap-1.5"
          >
            <Plus size={16} />
            {creating ? 'Creating…' : 'New Suite'}
          </button>
        </form>
      )}

      {loading ? (
        <CardSkeleton count={6} />
      ) : loadError ? (
        <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded-md px-4 py-3">
          <p>{loadError}</p>
          <button onClick={load} className="mt-2 text-red-800 font-medium hover:underline">
            Retry
          </button>
        </div>
      ) : suites.length === 0 ? (
        <EmptyState
          icon={BookOpen}
          title="No test suites yet"
          description="Create your first test suite to organize test cases."
        />
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {suites.map((s) => (
            <button
              key={s.id}
              onClick={() => navigate(`/${slug}/suites/${s.id}`)}
              className="text-left p-5 bg-white border border-gray-200 rounded-lg hover:shadow-md hover:border-emerald-300 transition"
            >
              <div className="flex items-center gap-2 flex-wrap">
                <h3 className="font-medium text-gray-900">{s.name}</h3>
                <StatusBadge status={s.status} />
              </div>
              <p className="text-xs text-gray-500 mt-1">{s.suite_type}</p>
              {s.description && <p className="text-xs text-gray-400 mt-2">{s.description}</p>}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
