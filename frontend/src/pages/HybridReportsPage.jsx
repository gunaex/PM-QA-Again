import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import {
  getHybridDashboard,
  getHybridLocatorFailures,
  getHybridFailureCategories,
  getHybridFrequentFailures,
  getHybridSlowestSteps,
  getRunTiming,
  listWorkflows,
  getRunDurationTrend,
  getStepDurationTrend,
} from '../api/client'

// HYB-5: hybrid (Track B) dashboard/reports/timing — a separate page from
// ReportsPage.jsx (Track A), which is left completely untouched. All data
// here comes from /hybrid-reports/*, never Track A's own /reports/*.

function KeyValueGrid({ obj }) {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
      {Object.entries(obj).map(([k, v]) => (
        <div key={k} className="bg-gray-50 rounded-md p-3">
          <p className="text-[10px] uppercase text-gray-400">{k}</p>
          <p className="text-sm font-medium text-gray-800">{typeof v === 'number' ? v : String(v)}</p>
        </div>
      ))}
    </div>
  )
}

function Table({ rows }) {
  if (!rows || rows.length === 0) return <p className="text-xs text-gray-400">No data yet.</p>
  const columns = Object.keys(rows[0])
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-gray-100 text-left text-gray-500 uppercase">
            {columns.map((c) => (
              <th key={c} className="px-3 py-2 whitespace-nowrap">{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-b border-gray-50">
              {columns.map((c) => (
                <td key={c} className="px-3 py-2 whitespace-nowrap max-w-xs truncate">
                  {typeof row[c] === 'object' && row[c] !== null ? JSON.stringify(row[c]) : String(row[c] ?? '—')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function HybridReportsPage() {
  const { slug } = useParams()
  const [dashboard, setDashboard] = useState(null)
  const [locatorFailures, setLocatorFailures] = useState([])
  const [failureCategories, setFailureCategories] = useState({})
  const [frequentFailures, setFrequentFailures] = useState([])
  const [slowestSteps, setSlowestSteps] = useState([])
  const [error, setError] = useState(null)

  const [workflows, setWorkflows] = useState([])
  const [workflowId, setWorkflowId] = useState('')
  const [stepDescription, setStepDescription] = useState('')
  const [runId, setRunId] = useState('')
  const [runTiming, setRunTiming] = useState(null)
  const [runTrend, setRunTrend] = useState(null)
  const [stepTrend, setStepTrend] = useState(null)

  useEffect(() => {
    Promise.all([
      getHybridDashboard(slug),
      getHybridLocatorFailures(slug),
      getHybridFailureCategories(slug),
      getHybridFrequentFailures(slug),
      getHybridSlowestSteps(slug),
      listWorkflows(slug),
    ])
      .then(([d, lf, fc, ff, ss, wf]) => {
        setDashboard(d)
        setLocatorFailures(lf)
        setFailureCategories(fc)
        setFrequentFailures(ff)
        setSlowestSteps(ss)
        setWorkflows(wf)
        if (wf.length > 0) setWorkflowId(String(wf[0].id))
      })
      .catch((err) => setError(err.response?.data?.detail || 'Could not load hybrid reports'))
  }, [slug])

  const loadRunTiming = async () => {
    if (!runId) return
    try {
      setRunTiming(await getRunTiming(slug, runId))
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not load run timing')
    }
  }

  const loadTrends = async () => {
    if (!workflowId) return
    try {
      setRunTrend(await getRunDurationTrend(slug, workflowId))
      if (stepDescription) setStepTrend(await getStepDurationTrend(slug, workflowId, stepDescription))
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not load trends')
    }
  }

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-semibold text-gray-900">Hybrid Reports &amp; Timing</h2>
      {error && <p className="text-sm text-red-600">{error}</p>}

      {dashboard && (
        <div className="bg-white border border-gray-200 rounded-lg p-5 space-y-4">
          <div>
            <p className="text-xs font-medium text-gray-500 uppercase mb-2">Run Status Counts</p>
            <KeyValueGrid obj={dashboard.run_status_counts} />
          </div>
          <div>
            <p className="text-xs font-medium text-gray-500 uppercase mb-2">Machine Step Outcomes</p>
            <KeyValueGrid obj={dashboard.provenance.machine_step_outcomes} />
          </div>
          <div>
            <p className="text-xs font-medium text-gray-500 uppercase mb-2">Human Checkpoint Decisions</p>
            <KeyValueGrid obj={dashboard.provenance.human_checkpoint_decisions} />
          </div>
          <div>
            <p className="text-xs font-medium text-gray-500 uppercase mb-2">Runner Reliability</p>
            <Table rows={dashboard.runner_reliability} />
          </div>
          <div>
            <p className="text-xs font-medium text-gray-500 uppercase mb-2">Checkpoint Waiting Summary (manual waiting time)</p>
            <KeyValueGrid obj={Object.fromEntries(Object.entries(dashboard.checkpoint_waiting_summary).map(([k, v]) => [k, v ?? '—']))} />
          </div>
          <div>
            <p className="text-xs font-medium text-gray-500 uppercase mb-2">Recent Hybrid Activity</p>
            <Table rows={dashboard.recent_activity} />
          </div>
        </div>
      )}

      <div className="bg-white border border-gray-200 rounded-lg p-5 space-y-4">
        <p className="text-xs font-medium text-gray-500 uppercase">Failure &amp; Reliability Reports</p>
        <div>
          <p className="text-xs text-gray-500 mb-1">Locator Failure Frequency</p>
          <Table rows={locatorFailures} />
        </div>
        <div>
          <p className="text-xs text-gray-500 mb-1">Failure Categories</p>
          <KeyValueGrid obj={failureCategories} />
        </div>
        <div>
          <p className="text-xs text-gray-500 mb-1">Workflows With Frequent Failures</p>
          <Table rows={frequentFailures} />
        </div>
        <div>
          <p className="text-xs text-gray-500 mb-1">Slowest Workflow Steps</p>
          <Table rows={slowestSteps} />
        </div>
      </div>

      <div className="bg-white border border-gray-200 rounded-lg p-5 space-y-3">
        <p className="text-xs font-medium text-gray-500 uppercase">Run Timing Detail</p>
        <div className="flex gap-2 items-end flex-wrap">
          <div>
            <label className="block text-xs text-gray-500 mb-1">Run ID</label>
            <input
              value={runId}
              onChange={(e) => setRunId(e.target.value)}
              className="px-3 py-2 border border-gray-300 rounded-md text-sm w-32"
            />
          </div>
          <button onClick={loadRunTiming} className="px-4 py-2 bg-emerald-600 text-white text-sm font-medium rounded-md hover:bg-emerald-700">
            Load Timing
          </button>
        </div>
        {runTiming && (
          <div className="space-y-3">
            <KeyValueGrid
              obj={{
                queue_delay_seconds: runTiming.queue_delay_seconds ?? '—',
                browser_startup_seconds: runTiming.browser_startup_seconds ?? '—',
                execution_duration_seconds: runTiming.execution_duration_seconds ?? '—',
                total_run_duration_seconds: runTiming.total_run_duration_seconds ?? '—',
                total_application_step_seconds: runTiming.total_application_step_seconds ?? '—',
                total_manual_waiting_seconds: runTiming.total_manual_waiting_seconds ?? '—',
              }}
            />
            <div>
              <p className="text-xs text-gray-500 mb-1">Per-Step Timing</p>
              <Table rows={runTiming.steps} />
            </div>
            <div>
              <p className="text-xs text-gray-500 mb-1">Checkpoint Timing</p>
              <Table rows={runTiming.checkpoints} />
            </div>
          </div>
        )}
      </div>

      <div className="bg-white border border-gray-200 rounded-lg p-5 space-y-3">
        <p className="text-xs font-medium text-gray-500 uppercase">Historical Trends</p>
        <div className="flex gap-2 items-end flex-wrap">
          <div>
            <label className="block text-xs text-gray-500 mb-1">Workflow</label>
            <select
              value={workflowId}
              onChange={(e) => setWorkflowId(e.target.value)}
              className="px-3 py-2 border border-gray-300 rounded-md text-sm"
            >
              {workflows.map((w) => (
                <option key={w.id} value={w.id}>{w.name}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">Step description (exact match, optional)</label>
            <input
              value={stepDescription}
              onChange={(e) => setStepDescription(e.target.value)}
              className="px-3 py-2 border border-gray-300 rounded-md text-sm w-64"
            />
          </div>
          <button onClick={loadTrends} className="px-4 py-2 bg-emerald-600 text-white text-sm font-medium rounded-md hover:bg-emerald-700">
            Load Trend
          </button>
        </div>
        {runTrend && (
          <div>
            <p className="text-xs text-gray-500 mb-1">Run Duration Trend (oldest → newest)</p>
            <Table rows={runTrend} />
          </div>
        )}
        {stepTrend && (
          <div>
            <p className="text-xs text-gray-500 mb-1">Step Duration Trend (oldest → newest)</p>
            <Table rows={stepTrend} />
          </div>
        )}
      </div>
    </div>
  )
}
