import { useEffect, useState } from 'react'
import { useParams, useOutletContext, useNavigate, NavLink } from 'react-router-dom'
import { getDashboard, getContinueLastTest } from '../api/client'
import StatusBadge from '../components/StatusBadge.jsx'
import StartTestingModal from '../components/StartTestingModal.jsx'

const TILE_LABELS = {
  NOT_RUN: 'Not Run',
  PASS: 'Pass',
  FAIL: 'NG',
  BLOCKED: 'Blocked',
  NOT_APPLICABLE: 'N/A',
}

export default function Dashboard() {
  const { slug } = useParams()
  const { project } = useOutletContext()
  const navigate = useNavigate()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [showStartTesting, setShowStartTesting] = useState(false)
  const [continueTarget, setContinueTarget] = useState(null)

  useEffect(() => {
    setLoading(true)
    getDashboard(slug)
      .then(setData)
      .catch(() => setError('Could not reach the backend.'))
      .finally(() => setLoading(false))
    getContinueLastTest(slug)
      .then(setContinueTarget)
      .catch(() => setContinueTarget(null))
  }, [slug])

  const startTestingButton = (
    <button
      onClick={() => setShowStartTesting(true)}
      className="px-4 py-2 bg-emerald-600 text-white text-sm font-medium rounded-md hover:bg-emerald-700"
    >
      Start Testing
    </button>
  )
  const continueButton = continueTarget && (
    <button
      onClick={() => navigate(`/${slug}/cycles/${continueTarget.cycle_id}?resultId=${continueTarget.result_id}`)}
      className="px-4 py-2 border border-emerald-300 text-emerald-700 text-sm font-medium rounded-md hover:bg-emerald-50"
    >
      Continue Last Test
    </button>
  )

  const projectCard = project && (
    <div className="bg-white border border-gray-200 rounded-lg p-4 flex items-center justify-between">
      <div>
        <p className="text-sm text-gray-900 font-medium">{project.name}</p>
        <p className="text-xs text-gray-500">{project.slug}</p>
      </div>
      {project.external_project_url && (
        <a href={project.external_project_url} target="_blank" rel="noreferrer" className="text-xs text-emerald-600 hover:underline">
          Back to PM-Again &rarr;
        </a>
      )}
    </div>
  )

  if (loading) return <p className="text-gray-500 text-sm">Loading…</p>
  if (error) return <p className="text-sm text-red-600">{error}</p>
  if (!data?.cycle)
    return (
      <div className="space-y-4">
        {projectCard}
        <div className="flex items-center gap-2 flex-wrap">
          {startTestingButton}
          {continueButton}
        </div>
        <p className="text-gray-500 text-sm">{data?.message || 'No data yet.'}</p>
        {showStartTesting && <StartTestingModal slug={slug} onClose={() => setShowStartTesting(false)} />}
      </div>
    )

  const { cycle, total_cases, result_counts, pass_rate, evidence_completeness, go_live_readiness, open_defects_by_severity, pending_na_reviews, storage_usage, recent_activity } = data

  return (
    <div className="space-y-6">
      {projectCard}
      <div className="flex items-center gap-2 flex-wrap">
        {startTestingButton}
        {continueButton}
      </div>
      <div className="flex items-center gap-2 flex-wrap">
        <h2 className="text-xl font-semibold text-gray-900">Dashboard</h2>
        <span className="text-sm text-gray-500">— {cycle.name}</span>
        <StatusBadge status={cycle.status} />
        <NavLink to={`/${slug}/cycles/${cycle.id}`} className="ml-auto text-sm text-emerald-600 hover:underline">
          Open execution screen &rarr;
        </NavLink>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        <div className="bg-white border border-gray-200 rounded-lg p-4">
          <p className="text-xs text-gray-500 uppercase">Total Cases</p>
          <p className="text-2xl font-semibold text-gray-900">{total_cases}</p>
        </div>
        {Object.entries(result_counts).map(([status, count]) => (
          <div key={status} className="bg-white border border-gray-200 rounded-lg p-4">
            <p className="text-xs text-gray-500 uppercase">{TILE_LABELS[status]}</p>
            <p className="text-2xl font-semibold text-gray-900">{count}</p>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div className="bg-white border border-gray-200 rounded-lg p-5" title={pass_rate.formula}>
          <p className="text-xs font-medium text-gray-500 uppercase">Pass Rate</p>
          <p className="text-3xl font-semibold text-gray-900 mt-1">{pass_rate.percent}%</p>
          <p className="text-xs text-gray-400 mt-1">
            {pass_rate.numerator} / {pass_rate.denominator} — {pass_rate.formula}
          </p>
        </div>
        <div className="bg-white border border-gray-200 rounded-lg p-5" title={evidence_completeness.formula}>
          <p className="text-xs font-medium text-gray-500 uppercase">Evidence Completeness</p>
          <p className="text-3xl font-semibold text-gray-900 mt-1">{evidence_completeness.percent}%</p>
          <p className="text-xs text-gray-400 mt-1">
            {evidence_completeness.numerator} / {evidence_completeness.denominator} — {evidence_completeness.formula}
          </p>
        </div>
      </div>

      <div className="bg-white border border-gray-200 rounded-lg p-5">
        <div className="flex items-center gap-2">
          <p className="text-sm font-medium text-gray-900">Go-Live Readiness</p>
          <span className={`px-2 py-0.5 rounded-full text-xs ${go_live_readiness.ready ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}`}>
            {go_live_readiness.ready ? 'READY' : 'NOT READY'}
          </span>
        </div>
        {go_live_readiness.blockers.length > 0 && (
          <ul className="mt-2 text-xs text-red-600 list-disc list-inside space-y-0.5">
            {go_live_readiness.blockers.map((b, i) => (
              <li key={i}>{b}</li>
            ))}
          </ul>
        )}
        <p className="text-xs text-gray-400 mt-2">{go_live_readiness.formula}</p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div className="bg-white border border-gray-200 rounded-lg p-5">
          <p className="text-sm font-medium text-gray-900 mb-2">Open Defects by Severity</p>
          <div className="flex gap-3 flex-wrap">
            {Object.entries(open_defects_by_severity).map(([sev, count]) => (
              <span key={sev} className="text-xs text-gray-600">
                {sev}: <span className="font-semibold text-gray-900">{count}</span>
              </span>
            ))}
          </div>
          <p className="text-xs text-gray-400 mt-2">Pending N/A reviews: {pending_na_reviews}</p>
        </div>
        <div className="bg-white border border-gray-200 rounded-lg p-5">
          <p className="text-sm font-medium text-gray-900 mb-2">Storage Usage</p>
          <div className="w-full bg-gray-100 rounded-full h-2">
            <div
              className={`h-2 rounded-full ${storage_usage.over_quota ? 'bg-red-500' : 'bg-emerald-500'}`}
              style={{ width: `${Math.min(storage_usage.percent_used, 100)}%` }}
            />
          </div>
          <p className="text-xs text-gray-400 mt-2">
            {storage_usage.percent_used}% of {(storage_usage.quota_bytes / 1024 / 1024 / 1024).toFixed(1)} GB
          </p>
        </div>
      </div>

      <div className="bg-white border border-gray-200 rounded-lg p-5">
        <p className="text-sm font-medium text-gray-900 mb-2">Recent Activity</p>
        {recent_activity.length === 0 ? (
          <p className="text-xs text-gray-400">No changes recorded yet.</p>
        ) : (
          <ul className="text-xs text-gray-600 space-y-1">
            {recent_activity.map((a, i) => (
              <li key={i}>
                {a.entity_type} #{a.entity_id}: {a.field_changed} changed by {a.changed_by} at {new Date(a.changed_at).toLocaleString()}
              </li>
            ))}
          </ul>
        )}
      </div>
      {showStartTesting && <StartTestingModal slug={slug} onClose={() => setShowStartTesting(false)} />}
    </div>
  )
}
