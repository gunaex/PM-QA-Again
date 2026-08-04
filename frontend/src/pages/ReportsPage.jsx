import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { PieChart, Pie, Cell, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
import {
  BarChart3, ChevronDown, ChevronRight, Download, FileSpreadsheet, FileArchive,
  CheckCircle, ShieldCheck, AlertTriangle, HardDrive, Users, Bug, GitCompare, Clock,
} from 'lucide-react'
import {
  listCycles, listSuites, listRevisions,
  getExecutionSummary, getDetailedResults, getNgDefects,
  getEvidenceCompletenessReport, getRevisionComparison, getCycleComparison,
  getTesterProgress, getGoLiveReadinessReport, getSignoffSummary,
  getStorageUsageReport, exportExcelUrl, exportZipUrl,
} from '../api/client'
import StatusBadge from '../components/StatusBadge.jsx'
import { DataTable, Timeline, DiffColumn } from '../components/reports/ReportVisuals.jsx'
import { DashboardSkeleton } from '../components/PageSkeleton.jsx'

// ─── Colors ─────────────────────────────────────────────────────────
const STATUS_COLORS = {
  PASS: '#059669', FAIL: '#DC2626', BLOCKED: '#D97706',
  NOT_APPLICABLE: '#6B7280', NOT_RUN: '#9CA3AF',
}
const STATUS_LABELS = { PASS: 'Pass', FAIL: 'Fail', BLOCKED: 'Blocked', NOT_APPLICABLE: 'N/A', NOT_RUN: 'Not Run' }

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

// ─── Donut Chart ────────────────────────────────────────────────────
function StatusDonut({ data }) {
  const chartData = Object.entries(data.result_counts || {})
    .filter(([, v]) => v > 0)
    .map(([status, count]) => ({ name: STATUS_LABELS[status] || status, value: count, color: STATUS_COLORS[status] || '#9CA3AF' }))
  const total = chartData.reduce((s, d) => s + d.value, 0)
  return (
    <div className="flex flex-col sm:flex-row items-center gap-6">
      <div className="w-48 h-48 shrink-0">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie data={chartData} cx="50%" cy="50%" innerRadius={55} outerRadius={85} paddingAngle={2} dataKey="value" stroke="none">
              {chartData.map((entry, i) => (<Cell key={i} fill={entry.color} />))}
            </Pie>
            <text x="50%" y="47%" textAnchor="middle" dominantBaseline="middle" style={{ fontSize: 24, fontWeight: 700, fill: '#111827' }}>{total}</text>
            <text x="50%" y="57%" textAnchor="middle" dominantBaseline="middle" style={{ fontSize: 12, fill: '#6B7280' }}>total cases</text>
          </PieChart>
        </ResponsiveContainer>
      </div>
      <div className="grid grid-cols-2 gap-x-5 gap-y-2">
        {chartData.map((d) => (
          <div key={d.name} className="flex items-center gap-2">
            <div className="w-3 h-3 rounded-sm shrink-0" style={{ backgroundColor: d.color }} />
            <span className="text-sm text-gray-600">{d.name}</span>
            <span className="text-sm font-semibold text-gray-900 ml-auto">{d.value}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ─── Tester Bar Chart ───────────────────────────────────────────────
function TesterBarChart({ data }) {
  if (!data || data.length === 0) return <p className="text-sm text-gray-400">No results executed yet.</p>
  const chartData = data.map((r) => ({
    name: (r.tester || 'Unknown').split('@')[0],
    Pass: r.counts?.PASS || 0, Fail: r.counts?.FAIL || 0,
    Blocked: r.counts?.BLOCKED || 0, 'N/A': r.counts?.NOT_APPLICABLE || 0,
  }))
  return (
    <div className="h-64">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={chartData} layout="vertical" margin={{ top: 0, right: 0, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#F3F4F6" horizontal={false} />
          <XAxis type="number" tick={{ fontSize: 12, fill: '#9CA3AF' }} />
          <YAxis type="category" dataKey="name" width={80} tick={{ fontSize: 12, fill: '#6B7280' }} />
          <Tooltip contentStyle={{ borderRadius: 8, border: '1px solid #E5E7EB', fontSize: 12 }} />
          <Bar dataKey="Pass" stackId="a" fill={STATUS_COLORS.PASS} />
          <Bar dataKey="Fail" stackId="a" fill={STATUS_COLORS.FAIL} />
          <Bar dataKey="Blocked" stackId="a" fill={STATUS_COLORS.BLOCKED} />
          <Bar dataKey="N/A" stackId="a" fill={STATUS_COLORS.NOT_APPLICABLE} radius={[0, 4, 4, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

// ─── Scorecard KPI ──────────────────────────────────────────────────
function Scorecard({ icon: Icon, label, value, sub, color = 'emerald' }) {
  return (
    <div className="bg-white border border-gray-200 rounded-xl p-5 hover:shadow-md transition">
      <div className="flex items-center gap-3 mb-2">
        <div className={`w-10 h-10 rounded-lg bg-${color}-50 flex items-center justify-center`}>
          <Icon size={20} className={`text-${color}-600`} />
        </div>
        <div>
          <p className="text-xs text-gray-500 uppercase tracking-wide">{label}</p>
          <p className="text-2xl font-bold text-gray-900">{value}</p>
        </div>
      </div>
      {sub && <p className="text-xs text-gray-400">{sub}</p>}
    </div>
  )
}

// ─── Main Page ──────────────────────────────────────────────────────
export default function ReportsPage() {
  const { slug } = useParams()
  const [cycles, setCycles] = useState([])
  const [cycleId, setCycleId] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  // Report data
  const [summary, setSummary] = useState(null)
  const [detailed, setDetailed] = useState(null)
  const [ngDefects, setNgDefects] = useState(null)
  const [evidenceComp, setEvidenceComp] = useState(null)
  const [testerProgress, setTesterProgress] = useState(null)
  const [goLive, setGoLive] = useState(null)
  const [signoff, setSignoff] = useState(null)
  const [storage, setStorage] = useState(null)

  // Comparison
  const [suites, setSuites] = useState([])
  const [suiteId, setSuiteId] = useState('')
  const [revisions, setRevisions] = useState([])
  const [revisionAId, setRevisionAId] = useState('')
  const [revisionBId, setRevisionBId] = useState('')
  const [revisionDiff, setRevisionDiff] = useState(null)
  const [cycleBId, setCycleBId] = useState('')
  const [cycleDiff, setCycleDiff] = useState(null)

  // Date range filter
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')

  useEffect(() => {
    listCycles(slug, true).then((c) => { setCycles(c); if (c.length > 0) setCycleId(String(c[0].id)) })
    listSuites(slug).then(setSuites)
  }, [slug])
  useEffect(() => { if (suiteId) listRevisions(slug, suiteId).then(setRevisions) }, [slug, suiteId])

  const loadAll = async () => {
    setLoading(true); setError(null)
    const dateParams = {}
    if (dateFrom) dateParams.date_from = dateFrom
    if (dateTo) dateParams.date_to = dateTo
    try {
      const [sum, comp, tester, live, sig, stor] = await Promise.all([
        getExecutionSummary(slug, cycleId, dateParams),
        getEvidenceCompletenessReport(slug, cycleId, dateParams),
        getTesterProgress(slug, cycleId, dateParams),
        getGoLiveReadinessReport(slug, cycleId, dateParams),
        getSignoffSummary(slug, cycleId, dateParams),
        getStorageUsageReport(slug),
      ])
      setSummary(sum); setEvidenceComp(comp); setTesterProgress(tester)
      setGoLive(live); setSignoff(sig); setStorage(stor)
      setDetailed(null); setNgDefects(null)
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not load reports')
    } finally { setLoading(false) }
  }

  const loadDetailed = async () => {
    if (detailed) return
    const dateParams = {}
    if (dateFrom) dateParams.date_from = dateFrom
    if (dateTo) dateParams.date_to = dateTo
    try { setDetailed(await getDetailedResults(slug, cycleId, dateParams)) } catch {}
  }
  const loadNgDefects = async () => {
    if (ngDefects) return
    const dateParams = {}
    if (dateFrom) dateParams.date_from = dateFrom
    if (dateTo) dateParams.date_to = dateTo
    try { setNgDefects(await getNgDefects(slug, cycleId, dateParams)) } catch {}
  }
  const loadRevisionDiff = async () => { if (revisionAId && revisionBId) try { setRevisionDiff(await getRevisionComparison(slug, revisionAId, revisionBId)) } catch {} }
  const loadCycleDiff = async () => { if (cycleBId) try { setCycleDiff(await getCycleComparison(slug, cycleId, cycleBId)) } catch {} }

  const usedGb = storage ? (storage.used_bytes / 1024 / 1024 / 1024).toFixed(2) : null
  const quotaGb = storage ? (storage.quota_bytes / 1024 / 1024 / 1024).toFixed(1) : null

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <BarChart3 size={22} className="text-emerald-600" />
          <h2 className="text-xl font-semibold text-gray-900">Reports</h2>
        </div>
        {cycleId && summary && (
          <div className="flex gap-2">
            <a href={exportExcelUrl(slug, cycleId)} className="px-3 py-1.5 text-sm border border-gray-300 rounded-lg hover:bg-gray-50 flex items-center gap-1.5 transition">
              <FileSpreadsheet size={14} /> Excel
            </a>
            <a href={exportZipUrl(slug, cycleId)} className="px-3 py-1.5 text-sm border border-gray-300 rounded-lg hover:bg-gray-50 flex items-center gap-1.5 transition">
              <FileArchive size={14} /> ZIP
            </a>
          </div>
        )}
      </div>

      {/* Cycle Picker */}
      <div className="bg-white border border-gray-200 rounded-xl p-4 flex flex-wrap gap-3 items-end shadow-sm">
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1">Test Cycle</label>
          <select value={cycleId} onChange={(e) => setCycleId(e.target.value)}
            className="px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500 min-w-[200px]">
            {cycles.map((c) => (<option key={c.id} value={c.id}>{c.name}</option>))}
          </select>
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1">Date From</label>
          <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)}
            className="px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500" />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1">Date To</label>
          <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)}
            className="px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500" />
        </div>
        {(dateFrom || dateTo) && (
          <button onClick={() => { setDateFrom(''); setDateTo('') }}
            className="px-3 py-2 text-sm text-gray-500 hover:text-gray-700 border border-gray-200 rounded-lg hover:bg-gray-50 transition">
            Clear dates
          </button>
        )}
        <button onClick={loadAll} disabled={loading || !cycleId}
          className="px-5 py-2 bg-emerald-600 text-white text-sm font-medium rounded-lg hover:bg-emerald-700 disabled:opacity-50 flex items-center gap-2 transition">
          <Download size={16} />
          {loading ? 'Loading…' : 'Generate Report'}
        </button>
      </div>

      {error && <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded-lg px-4 py-3">{error}</div>}
      {loading && <DashboardSkeleton />}

      {/* Report Content */}
      {summary && !loading && (
        <div className="space-y-5">
          {/* ═══ SCORECARD ═══ */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <Scorecard icon={CheckCircle} label="Pass Rate" value={`${summary.pass_rate?.percent || 0}%`}
              sub={`${summary.pass_rate?.numerator}/${summary.pass_rate?.denominator} passed`}
              color={summary.pass_rate?.percent >= 90 ? 'emerald' : summary.pass_rate?.percent >= 70 ? 'amber' : 'red'} />
            <Scorecard icon={ShieldCheck} label="Evidence" value={`${evidenceComp?.percent || 0}%`}
              sub={`${evidenceComp?.numerator}/${evidenceComp?.denominator} complete`}
              color={evidenceComp?.percent >= 100 ? 'emerald' : 'amber'} />
            <Scorecard icon={AlertTriangle} label="Go-Live" value={goLive?.ready ? 'READY ✅' : 'NOT READY ❌'}
              sub={goLive?.ready ? 'No blockers' : `${goLive?.blockers?.length || 0} blocker(s)`}
              color={goLive?.ready ? 'emerald' : 'red'} />
            <Scorecard icon={HardDrive} label="Storage" value={usedGb ? `${usedGb} GB` : '—'}
              sub={`of ${quotaGb || '?'} GB`} color={storage?.over_quota ? 'red' : 'emerald'} />
          </div>

          {/* ═══ STATUS DISTRIBUTION ═══ */}
          <Section icon={CheckCircle} title="Status Distribution" subtitle="How cases are distributed across statuses">
            <StatusDonut data={summary} />
          </Section>

          {/* ═══ TESTER PROGRESS ═══ */}
          <Section icon={Users} title="Tester Progress" subtitle={`${testerProgress?.length || 0} tester(s)`}>
            <TesterBarChart data={testerProgress} />
          </Section>

          {/* ═══ DETAILED RESULTS (lazy) ═══ */}
          <Section icon={FileSpreadsheet} title="Detailed Results" subtitle="Every case result" defaultOpen={false}>
            <button onClick={loadDetailed} className="mb-3 px-4 py-2 text-sm bg-emerald-600 text-white rounded-lg hover:bg-emerald-700">
              {detailed ? '✓ Loaded' : 'Load Detailed Results'}
            </button>
            {detailed && <DataTable rows={detailed} emptyLabel="No results yet." />}
          </Section>

          {/* ═══ NG & DEFECTS (lazy) ═══ */}
          <Section icon={Bug} title="Failed Cases & Defects" subtitle="What needs attention" defaultOpen={false}>
            <button onClick={loadNgDefects} className="mb-3 px-4 py-2 text-sm bg-emerald-600 text-white rounded-lg hover:bg-emerald-700">
              {ngDefects ? '✓ Loaded' : 'Load NG & Defects'}
            </button>
            {ngDefects && (
              <div className="space-y-4">
                <div>
                  <p className="text-xs font-medium text-gray-500 uppercase mb-2">Failed ({ngDefects.ng_cases?.length || 0})</p>
                  <DataTable rows={ngDefects.ng_cases} emptyLabel="No failing cases — great!" />
                </div>
                <div>
                  <p className="text-xs font-medium text-gray-500 uppercase mb-2">Defects ({ngDefects.defects?.length || 0})</p>
                  <DataTable rows={ngDefects.defects} emptyLabel="No defects." />
                </div>
              </div>
            )}
          </Section>

          {/* ═══ COMPARISONS ═══ */}
          <Section icon={GitCompare} title="Comparisons" subtitle="Revision & cycle diffs" defaultOpen={false}>
            <div className="space-y-4">
              <div className="bg-gray-50 rounded-lg p-4">
                <p className="text-xs font-medium text-gray-500 uppercase mb-2">Revision Comparison</p>
                <div className="flex flex-wrap gap-2 mb-3">
                  <select value={suiteId} onChange={(e) => setSuiteId(e.target.value)} className="px-3 py-1.5 border rounded text-sm">
                    <option value="">Suite…</option>
                    {suites.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                  </select>
                  <select value={revisionAId} onChange={(e) => setRevisionAId(e.target.value)} className="px-3 py-1.5 border rounded text-sm">
                    <option value="">Rev A…</option>
                    {revisions.map((r) => <option key={r.id} value={r.id}>{r.revision_label}</option>)}
                  </select>
                  <select value={revisionBId} onChange={(e) => setRevisionBId(e.target.value)} className="px-3 py-1.5 border rounded text-sm">
                    <option value="">Rev B…</option>
                    {revisions.map((r) => <option key={r.id} value={r.id}>{r.revision_label}</option>)}
                  </select>
                  <button onClick={loadRevisionDiff} disabled={!revisionAId || !revisionBId}
                    className="px-3 py-1.5 bg-emerald-600 text-white text-sm rounded hover:bg-emerald-700 disabled:opacity-50">Compare</button>
                </div>
                {revisionDiff && (
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                    <DiffColumn title="Added" items={revisionDiff.added} tone="green" />
                    <DiffColumn title="Removed" items={revisionDiff.removed} tone="red" />
                    <DiffColumn title="Changed" items={revisionDiff.changed} tone="amber" />
                    <DiffColumn title="Unchanged" items={revisionDiff.unchanged} tone="gray" />
                  </div>
                )}
              </div>
              <div className="bg-gray-50 rounded-lg p-4">
                <p className="text-xs font-medium text-gray-500 uppercase mb-2">Cycle Comparison</p>
                <div className="flex flex-wrap gap-2 mb-3">
                  <select value={cycleBId} onChange={(e) => setCycleBId(e.target.value)} className="px-3 py-1.5 border rounded text-sm">
                    <option value="">Cycle B…</option>
                    {cycles.filter((c) => String(c.id) !== cycleId).map((c) => (<option key={c.id} value={c.id}>{c.name}</option>))}
                  </select>
                  <button onClick={loadCycleDiff} disabled={!cycleBId}
                    className="px-3 py-1.5 bg-emerald-600 text-white text-sm rounded hover:bg-emerald-700 disabled:opacity-50">Compare</button>
                </div>
                {cycleDiff && (
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs">
                      <thead><tr className="border-b border-gray-200 text-left text-gray-500 uppercase">
                        <th className="px-3 py-2">Checkpoint</th><th className="px-3 py-2">From</th><th className="px-3 py-2"></th><th className="px-3 py-2">To</th>
                      </tr></thead>
                      <tbody>
                        {cycleDiff.map((row) => (
                          <tr key={row.checkpoint_code} className={`border-b border-gray-100 ${row.changed ? 'bg-amber-50' : ''}`}>
                            <td className="px-3 py-2 font-mono">{row.checkpoint_code}</td>
                            <td className="px-3 py-2">{row.from === 'ABSENT' ? <span className="text-gray-300">—</span> : <StatusBadge status={row.from} />}</td>
                            <td className="px-3 py-2 text-gray-300">→</td>
                            <td className="px-3 py-2">{row.to === 'ABSENT' ? <span className="text-gray-300">—</span> : <StatusBadge status={row.to} />}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </div>
          </Section>

          {/* ═══ AUDIT TRAIL ═══ */}
          <Section icon={Clock} title="Audit Trail" subtitle="Sign-off history" defaultOpen={false}>
            {signoff && signoff.length > 0 ? (
              <Timeline items={signoff} renderItem={(s) => (
                <div className="bg-gray-50 rounded-lg p-3 border border-gray-200">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-sm font-medium text-gray-900">{s.signoff_type}</span>
                    <StatusBadge status={s.decision} />
                    <span className="text-xs text-gray-400 ml-auto">{s.acted_at ? new Date(s.acted_at).toLocaleString() : '—'}</span>
                  </div>
                  <p className="text-xs text-gray-500 mt-1">by {s.actor}</p>
                  {s.comment_md && <p className="text-xs text-gray-600 mt-1 whitespace-pre-wrap">{s.comment_md}</p>}
                </div>
              )} />
            ) : <p className="text-sm text-gray-400">No sign-off events yet.</p>}
          </Section>

          {/* ═══ STORAGE ═══ */}
          <Section icon={HardDrive} title="Storage Details" subtitle="Project evidence quota" defaultOpen={false}>
            {storage && (
              <div className="bg-white border border-gray-200 rounded-lg p-5">
                <p className="text-xs font-medium text-gray-500 uppercase">Storage Used</p>
                <p className="text-3xl font-semibold text-gray-900 mt-1">{storage.percent_used}%</p>
                <div className="w-full bg-gray-100 rounded-full h-2.5 mt-2">
                  <div className={`h-2.5 rounded-full ${storage.over_quota ? 'bg-red-500' : 'bg-emerald-500'}`}
                    style={{ width: `${Math.min(storage.percent_used, 100)}%` }} />
                </div>
                <p className="text-xs text-gray-400 mt-2">{usedGb} GB / {quotaGb} GB</p>
              </div>
            )}
            {storage?.over_quota && (
              <div className="mt-3 bg-red-50 border border-red-200 rounded-lg p-3 text-xs text-red-700">⚠ Over quota — uploads may be rejected.</div>
            )}
          </Section>
        </div>
      )}
    </div>
  )
}
