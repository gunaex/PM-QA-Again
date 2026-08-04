import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, BarChart, Bar } from 'recharts'
import {
  Activity, ChevronDown, ChevronRight, Bot, AlertTriangle, Clock, TrendingUp, Zap, Wifi, WifiOff,
} from 'lucide-react'
import {
  getHybridDashboard, getHybridLocatorFailures, getHybridFailureCategories,
  getHybridFrequentFailures, getHybridSlowestSteps, getRunTiming,
  listWorkflows, getRunDurationTrend, getStepDurationTrend,
} from '../api/client'
import StatusBadge from '../components/StatusBadge.jsx'
import { DashboardSkeleton } from '../components/PageSkeleton.jsx'

// ─── Collapsible Section ────────────────────────────────────────────
function Section({ icon: Icon, title, subtitle, defaultOpen = true, children }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="bg-white border border-gray-200 rounded-xl overflow-hidden shadow-sm">
      <button onClick={() => setOpen(!open)} className="w-full flex items-center justify-between px-5 py-4 hover:bg-gray-50 transition">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-lg bg-emerald-50 flex items-center justify-center">
            <Icon size={18} className="text-emerald-600" />
          </div>
          <div className="text-left">
            <h3 className="text-sm font-semibold text-gray-900">{title}</h3>
            {subtitle && <p className="text-xs text-gray-500">{subtitle}</p>}
          </div>
        </div>
        {open ? <ChevronDown size={18} className="text-gray-400" /> : <ChevronRight size={18} className="text-gray-400" />}
      </button>
      {open && <div className="px-5 pb-5 border-t border-gray-100 pt-4">{children}</div>}
    </div>
  )
}

// ─── Mini KPI Tile ──────────────────────────────────────────────────
function KpiTile({ label, value, color = 'gray' }) {
  return (
    <div className="bg-gray-50 rounded-lg p-3 text-center">
      <p className="text-[10px] uppercase text-gray-400">{label}</p>
      <p className={`text-lg font-bold text-${color === 'green' ? 'emerald' : color === 'red' ? 'red' : color === 'amber' ? 'amber' : 'gray'}-700`}>
        {typeof value === 'number' ? value.toLocaleString() : String(value ?? '—')}
      </p>
    </div>
  )
}

// ─── Run Duration Trend Chart ───────────────────────────────────────
function RunTrendChart({ data }) {
  if (!data || data.length === 0) return <p className="text-sm text-gray-400">No trend data.</p>
  const chartData = data.map((d, i) => ({
    name: d.run_label || `#${i + 1}`,
    seconds: d.duration_seconds || d.total_run_duration_seconds || 0,
  }))
  return (
    <div className="h-56">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={chartData}>
          <CartesianGrid strokeDasharray="3 3" stroke="#F3F4F6" />
          <XAxis dataKey="name" tick={{ fontSize: 11, fill: '#9CA3AF' }} />
          <YAxis tick={{ fontSize: 11, fill: '#9CA3AF' }} />
          <Tooltip contentStyle={{ borderRadius: 8, border: '1px solid #E5E7EB', fontSize: 12 }}
            formatter={(v) => [`${Number(v).toFixed(1)}s`, 'Duration']} />
          <Line type="monotone" dataKey="seconds" stroke="#059669" strokeWidth={2} dot={{ r: 3, fill: '#059669' }} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

// ─── Simple Table ───────────────────────────────────────────────────
function SimpleTable({ rows }) {
  if (!rows || rows.length === 0) return <p className="text-xs text-gray-400">No data yet.</p>
  const columns = Object.keys(rows[0])
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-gray-100 text-left text-gray-500 uppercase">
            {columns.map((c) => (<th key={c} className="px-3 py-2 whitespace-nowrap">{c.replace(/_/g, ' ')}</th>))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-b border-gray-50 hover:bg-gray-50">
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

// ─── Main ───────────────────────────────────────────────────────────
export default function HybridReportsPage() {
  const { slug } = useParams()
  const [dashboard, setDashboard] = useState(null)
  const [locatorFailures, setLocatorFailures] = useState([])
  const [failureCategories, setFailureCategories] = useState({})
  const [frequentFailures, setFrequentFailures] = useState([])
  const [slowestSteps, setSlowestSteps] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const [workflows, setWorkflows] = useState([])
  const [workflowId, setWorkflowId] = useState('')
  const [stepDescription, setStepDescription] = useState('')
  const [runId, setRunId] = useState('')
  const [runTiming, setRunTiming] = useState(null)
  const [runTrend, setRunTrend] = useState(null)
  const [stepTrend, setStepTrend] = useState(null)

  useEffect(() => {
    setLoading(true)
    Promise.all([
      getHybridDashboard(slug), getHybridLocatorFailures(slug),
      getHybridFailureCategories(slug), getHybridFrequentFailures(slug),
      getHybridSlowestSteps(slug), listWorkflows(slug),
    ])
      .then(([d, lf, fc, ff, ss, wf]) => {
        setDashboard(d); setLocatorFailures(lf); setFailureCategories(fc)
        setFrequentFailures(ff); setSlowestSteps(ss); setWorkflows(wf)
        if (wf.length > 0) setWorkflowId(String(wf[0].id))
      })
      .catch((err) => setError(err.response?.data?.detail || 'Could not load hybrid reports'))
      .finally(() => setLoading(false))
  }, [slug])

  const loadRunTiming = async () => { if (!runId) return; try { setRunTiming(await getRunTiming(slug, runId)) } catch {} }
  const loadTrends = async () => {
    if (!workflowId) return
    try {
      setRunTrend(await getRunDurationTrend(slug, workflowId))
      if (stepDescription) setStepTrend(await getStepDurationTrend(slug, workflowId, stepDescription))
    } catch {}
  }

  const statusCounts = dashboard?.run_status_counts || {}
  const passed = statusCounts.PASSED || 0
  const failed = statusCounts.FAILED || 0
  const total = Object.values(statusCounts).reduce((s, v) => s + (typeof v === 'number' ? v : 0), 0)

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Activity size={22} className="text-emerald-600" />
        <h2 className="text-xl font-semibold text-gray-900">Hybrid Reports</h2>
      </div>

      {error && <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded-lg px-4 py-3">{error}</div>}
      {loading && <DashboardSkeleton />}

      {!loading && dashboard && (
        <div className="space-y-5">
          {/* ═══ SCORECARD ═══ */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <KpiTile label="Total Runs" value={total} color="gray" />
            <KpiTile label="Passed" value={passed} color="green" />
            <KpiTile label="Failed" value={failed} color="red" />
            <KpiTile label="Success Rate" value={total > 0 ? `${((passed / total) * 100).toFixed(0)}%` : '—'} color={passed / total >= 0.9 ? 'green' : 'amber'} />
          </div>

          {/* ═══ RUN STATUS BREAKDOWN ═══ */}
          <Section icon={Bot} title="Run Status Breakdown" subtitle="Automated workflow execution results">
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              {Object.entries(statusCounts).map(([k, v]) => (
                <KpiTile key={k} label={k.replace(/_/g, ' ')} value={v} color={k === 'PASSED' ? 'green' : k === 'FAILED' ? 'red' : 'gray'} />
              ))}
            </div>
            <div className="mt-3 grid grid-cols-2 gap-3">
              <div>
                <p className="text-xs font-medium text-gray-500 uppercase mb-2">Machine Steps</p>
                <div className="grid grid-cols-2 gap-2">
                  {Object.entries(dashboard.provenance?.machine_step_outcomes || {}).map(([k, v]) => (
                    <KpiTile key={k} label={k.replace(/_/g, ' ')} value={v} />
                  ))}
                </div>
              </div>
              <div>
                <p className="text-xs font-medium text-gray-500 uppercase mb-2">Human Checkpoints</p>
                <div className="grid grid-cols-2 gap-2">
                  {Object.entries(dashboard.provenance?.human_checkpoint_decisions || {}).map(([k, v]) => (
                    <KpiTile key={k} label={k.replace(/_/g, ' ')} value={v} />
                  ))}
                </div>
              </div>
            </div>
          </Section>

          {/* ═══ RUNNER RELIABILITY ═══ */}
          <Section icon={Wifi} title="Runner Reliability" subtitle="Which runners are stable vs failing" defaultOpen={false}>
            {dashboard.runner_reliability?.length > 0 ? (
              <div className="space-y-2">
                {dashboard.runner_reliability.map((r, i) => (
                  <div key={i} className="flex items-center justify-between bg-gray-50 rounded-lg p-3">
                    <div className="flex items-center gap-2">
                      {r.failure_rate > 0.2 ? <WifiOff size={14} className="text-red-500" /> : <Wifi size={14} className="text-emerald-500" />}
                      <span className="text-sm font-medium text-gray-800">{r.runner_label || r.runner_token?.slice(0, 12) || `Runner ${i + 1}`}</span>
                    </div>
                    <div className="flex items-center gap-3 text-xs">
                      <span className="text-gray-500">{r.total_runs || 0} runs</span>
                      <span className={`font-semibold ${r.failure_rate > 0.2 ? 'text-red-600' : 'text-emerald-600'}`}>
                        {r.failure_rate != null ? `${(r.failure_rate * 100).toFixed(0)}% fail` : '—'}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            ) : <p className="text-sm text-gray-400">No runner data yet.</p>}
          </Section>

          {/* ═══ FAILURE ANALYSIS ═══ */}
          <Section icon={AlertTriangle} title="Failure Analysis" subtitle="Locator failures, categories, and frequent issues" defaultOpen={false}>
            <div className="space-y-4">
              {Object.keys(failureCategories).length > 0 && (
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                  {Object.entries(failureCategories).map(([k, v]) => (
                    <KpiTile key={k} label={k} value={v} color={v > 0 ? 'amber' : 'gray'} />
                  ))}
                </div>
              )}
              {locatorFailures.length > 0 && (
                <div>
                  <p className="text-xs font-medium text-gray-500 uppercase mb-2">Locator Failures</p>
                  <SimpleTable rows={locatorFailures} />
                </div>
              )}
              {frequentFailures.length > 0 && (
                <div>
                  <p className="text-xs font-medium text-gray-500 uppercase mb-2">Frequent Failures</p>
                  <SimpleTable rows={frequentFailures} />
                </div>
              )}
            </div>
          </Section>

          {/* ═══ SLOWEST STEPS ═══ */}
          <Section icon={Zap} title="Slowest Steps" subtitle="Bottlenecks in automated workflows" defaultOpen={false}>
            <SimpleTable rows={slowestSteps} />
          </Section>

          {/* ═══ RUN TIMING ═══ */}
          <Section icon={Clock} title="Run Timing Detail" subtitle="Per-run breakdown" defaultOpen={false}>
            <div className="flex gap-2 items-end flex-wrap mb-3">
              <div>
                <label className="block text-xs text-gray-500 mb-1">Run ID</label>
                <input value={runId} onChange={(e) => setRunId(e.target.value)}
                  className="px-3 py-2 border border-gray-300 rounded-lg text-sm w-40" />
              </div>
              <button onClick={loadRunTiming} className="px-4 py-2 bg-emerald-600 text-white text-sm rounded-lg hover:bg-emerald-700">
                Load
              </button>
            </div>
            {runTiming && (
              <div className="space-y-3">
                <div className="grid grid-cols-3 gap-2">
                  <KpiTile label="Queue" value={`${runTiming.queue_delay_seconds ?? '—'}s`} />
                  <KpiTile label="Browser" value={`${runTiming.browser_startup_seconds ?? '—'}s`} />
                  <KpiTile label="Execution" value={`${runTiming.execution_duration_seconds ?? '—'}s`} />
                  <KpiTile label="Total" value={`${runTiming.total_run_duration_seconds ?? '—'}s`} />
                  <KpiTile label="Auto Steps" value={`${runTiming.total_application_step_seconds ?? '—'}s`} />
                  <KpiTile label="Manual Wait" value={`${runTiming.total_manual_waiting_seconds ?? '—'}s`} />
                </div>
                {runTiming.steps && <SimpleTable rows={runTiming.steps} />}
              </div>
            )}
          </Section>

          {/* ═══ HISTORICAL TRENDS ═══ */}
          <Section icon={TrendingUp} title="Historical Trends" subtitle="Duration trends over time" defaultOpen={false}>
            <div className="flex gap-2 items-end flex-wrap mb-3">
              <div>
                <label className="block text-xs text-gray-500 mb-1">Workflow</label>
                <select value={workflowId} onChange={(e) => setWorkflowId(e.target.value)}
                  className="px-3 py-2 border border-gray-300 rounded-lg text-sm">
                  {workflows.map((w) => (<option key={w.id} value={w.id}>{w.name}</option>))}
                </select>
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">Step (optional)</label>
                <input value={stepDescription} onChange={(e) => setStepDescription(e.target.value)}
                  className="px-3 py-2 border border-gray-300 rounded-lg text-sm w-48" />
              </div>
              <button onClick={loadTrends} className="px-4 py-2 bg-emerald-600 text-white text-sm rounded-lg hover:bg-emerald-700">
                Load Trends
              </button>
            </div>
            {runTrend && <RunTrendChart data={runTrend} />}
            {stepTrend && (
              <div className="mt-4">
                <p className="text-xs font-medium text-gray-500 uppercase mb-2">Step Duration Trend</p>
                <SimpleTable rows={stepTrend} />
              </div>
            )}
          </Section>
        </div>
      )}
    </div>
  )
}
