import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import {
  listCycles,
  listSuites,
  listRevisions,
  getExecutionSummary,
  getDetailedResults,
  getNgDefects,
  getEvidenceCompletenessReport,
  getRevisionComparison,
  getCycleComparison,
  getTesterProgress,
  getGoLiveReadinessReport,
  getSignoffSummary,
  getStorageUsageReport,
  exportExcelUrl,
  exportZipUrl,
} from '../api/client'
import StatusBadge from '../components/StatusBadge.jsx'
import {
  ProgressStat,
  ReadinessCard,
  ResultCountTiles,
  DataTable,
  Timeline,
  DiffColumn,
  BlockerList,
  DeveloperData,
} from '../components/reports/ReportVisuals.jsx'

// One consolidated Reports page instead of 10 separate screens — see
// docs/ROADMAP.md Phase 6 for why (the spec names 10 reports; all 10
// exist as real backend endpoints, but a dedicated page per report is
// disproportionate for this MVP and duplicates the Excel export). Each
// report type renders as a purpose-built visual (KPI cards, badges,
// progress bars, tables, timelines, or blocker lists) with a one-line
// explanation of what it's for — the underlying API response is always
// available too, collapsed behind "Show Developer Data".
const REPORT_TYPES = [
  {
    value: 'execution-summary',
    label: 'Execution Summary',
    description: 'How many cases landed in each status this cycle, plus pass rate and evidence completeness at a glance.',
  },
  {
    value: 'detailed-results',
    label: 'Detailed Test Results',
    description: 'Every case in this cycle with its result, who ran it, when, and how much evidence was attached.',
  },
  {
    value: 'ng-defects',
    label: 'NG and Defect Report',
    description: 'Every FAILing case this cycle, alongside the defects logged against it — use this to see what still needs a fix.',
  },
  {
    value: 'evidence-completeness',
    label: 'Evidence Completeness',
    description: 'What fraction of executed cases have at least one piece of evidence attached, and which ones are still missing it.',
  },
  {
    value: 'revision-comparison',
    label: 'Revision Comparison',
    description: 'What changed between two suite revisions — cases added, removed, changed, or left untouched.',
  },
  {
    value: 'cycle-comparison',
    label: 'Cycle-to-Cycle Comparison',
    description: 'How each checkpoint’s result moved between two cycles — useful for spotting regressions after a fix.',
  },
  {
    value: 'tester-progress',
    label: 'Tester Progress',
    description: 'How much each tester has executed this cycle, broken down by result status.',
  },
  {
    value: 'go-live-readiness',
    label: 'Go-Live Readiness',
    description: 'A single READY/NOT READY call for this cycle, and the exact blockers holding it back if not.',
  },
  {
    value: 'signoff-summary',
    label: 'Audit/Sign-off Summary',
    description: 'The sign-off decision trail for this cycle — who approved or rejected it, and when.',
  },
  {
    value: 'storage-usage',
    label: 'Project Storage Usage',
    description: "This project's evidence storage against its quota, project-wide (not scoped to one cycle).",
  },
]

const REPORT_META = Object.fromEntries(REPORT_TYPES.map((r) => [r.value, r]))

function ExecutionSummaryView({ data }) {
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 flex-wrap">
        <p className="text-sm font-medium text-gray-900">{data.cycle.name}</p>
        <StatusBadge status={data.cycle.status} />
        <span className="text-xs text-gray-400">{data.cycle.environment}</span>
      </div>
      <ResultCountTiles counts={data.result_counts} />
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <ProgressStat
          label="Pass Rate"
          percent={data.pass_rate.percent}
          numerator={data.pass_rate.numerator}
          denominator={data.pass_rate.denominator}
          formula={data.pass_rate.formula}
        />
        <ProgressStat
          label="Evidence Completeness"
          percent={data.evidence_completeness.percent}
          numerator={data.evidence_completeness.numerator}
          denominator={data.evidence_completeness.denominator}
          formula={data.evidence_completeness.formula}
        />
      </div>
    </div>
  )
}

function NgDefectsView({ data }) {
  return (
    <div className="space-y-5">
      <div>
        <p className="text-xs font-medium text-gray-500 uppercase mb-1">NG Cases ({data.ng_cases.length})</p>
        <DataTable rows={data.ng_cases} emptyLabel="No failing cases in this cycle." />
      </div>
      <div>
        <p className="text-xs font-medium text-gray-500 uppercase mb-1">Defects ({data.defects.length})</p>
        <DataTable rows={data.defects} emptyLabel="No defects logged for this cycle." />
      </div>
    </div>
  )
}

function EvidenceCompletenessView({ data }) {
  return (
    <div className="space-y-4">
      <ProgressStat
        label="Evidence Completeness"
        percent={data.percent}
        numerator={data.numerator}
        denominator={data.denominator}
        formula={data.formula}
        danger={data.percent < 100}
      />
      <BlockerList
        title={`Missing Evidence (${data.missing_evidence_checkpoints.length})`}
        items={data.missing_evidence_checkpoints}
        emptyLabel="Every executed case has at least one piece of evidence."
      />
    </div>
  )
}

function RevisionComparisonView({ data }) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
      <DiffColumn title="Added" items={data.added} tone="green" />
      <DiffColumn title="Removed" items={data.removed} tone="red" />
      <DiffColumn title="Changed" items={data.changed} tone="amber" />
      <DiffColumn title="Unchanged" items={data.unchanged} tone="gray" />
    </div>
  )
}

function CycleComparisonView({ data }) {
  const changedCount = data.filter((row) => row.changed).length
  return (
    <div className="space-y-3">
      <p className="text-xs text-gray-500">
        {changedCount} of {data.length} checkpoint{data.length === 1 ? '' : 's'} changed status between the two cycles.
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-gray-100 text-left text-gray-500 uppercase">
              <th className="px-3 py-2">Checkpoint</th>
              <th className="px-3 py-2">From</th>
              <th className="px-3 py-2"></th>
              <th className="px-3 py-2">To</th>
            </tr>
          </thead>
          <tbody>
            {data.map((row) => (
              <tr key={row.checkpoint_code} className={`border-b border-gray-50 ${row.changed ? 'bg-amber-50' : ''}`}>
                <td className="px-3 py-2 font-mono whitespace-nowrap">{row.checkpoint_code}</td>
                <td className="px-3 py-2">
                  {row.from === 'ABSENT' ? <span className="text-gray-300">absent</span> : <StatusBadge status={row.from} />}
                </td>
                <td className="px-3 py-2 text-gray-300">&rarr;</td>
                <td className="px-3 py-2">
                  {row.to === 'ABSENT' ? <span className="text-gray-300">absent</span> : <StatusBadge status={row.to} />}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function TesterProgressView({ data }) {
  return (
    <div className="space-y-3">
      {data.length === 0 && <p className="text-xs text-gray-400">No results executed yet this cycle.</p>}
      {data.map((row) => (
        <div key={row.tester} className="bg-white border border-gray-200 rounded-lg p-4">
          <div className="flex items-center justify-between mb-2">
            <p className="text-sm font-medium text-gray-900">{row.tester}</p>
            <p className="text-xs text-gray-500">{row.total_executed} executed</p>
          </div>
          <div className="flex gap-3 flex-wrap">
            {Object.entries(row.counts)
              .filter(([, count]) => count > 0)
              .map(([status, count]) => (
                <span key={status} className="text-xs text-gray-600 flex items-center gap-1">
                  <StatusBadge status={status} /> <span className="font-semibold text-gray-900">{count}</span>
                </span>
              ))}
          </div>
        </div>
      ))}
    </div>
  )
}

function SignoffSummaryView({ data }) {
  return (
    <Timeline
      items={data}
      renderItem={(s) => (
        <div className="bg-white border border-gray-200 rounded-lg p-3">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-medium text-gray-900">{s.signoff_type}</span>
            <StatusBadge status={s.decision} />
            <span className="text-xs text-gray-400 ml-auto">{s.acted_at ? new Date(s.acted_at).toLocaleString() : '—'}</span>
          </div>
          <p className="text-xs text-gray-500 mt-1">by {s.actor}</p>
          {s.comment_md && <p className="text-xs text-gray-600 mt-1 whitespace-pre-wrap">{s.comment_md}</p>}
        </div>
      )}
    />
  )
}

function StorageUsageView({ data }) {
  const usedGb = (data.used_bytes / 1024 / 1024 / 1024).toFixed(2)
  const quotaGb = (data.quota_bytes / 1024 / 1024 / 1024).toFixed(1)
  return (
    <div className="space-y-4">
      <ProgressStat
        label="Storage Used"
        percent={data.percent_used}
        numerator={`${usedGb} GB`}
        denominator={`${quotaGb} GB quota`}
        formula={`Warning thresholds: ${data.thresholds.join('%, ')}%`}
        danger={data.over_quota || data.percent_used >= (data.thresholds[data.thresholds.length - 1] || 100)}
      />
      {data.over_quota && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-xs text-red-700">
          This project is over its storage quota. New evidence uploads may be rejected until usage drops or the quota is raised.
        </div>
      )}
    </div>
  )
}

function GoLiveReadinessView({ data }) {
  return <ReadinessCard ready={data.ready} blockers={data.blockers} formula={data.formula} />
}

function DetailedResultsView({ data }) {
  return <DataTable rows={data} emptyLabel="No results recorded for this cycle yet." />
}

function renderReportBody(reportType, data) {
  switch (reportType) {
    case 'execution-summary':
      return <ExecutionSummaryView data={data} />
    case 'detailed-results':
      return <DetailedResultsView data={data} />
    case 'ng-defects':
      return <NgDefectsView data={data} />
    case 'evidence-completeness':
      return <EvidenceCompletenessView data={data} />
    case 'revision-comparison':
      return <RevisionComparisonView data={data} />
    case 'cycle-comparison':
      return <CycleComparisonView data={data} />
    case 'tester-progress':
      return <TesterProgressView data={data} />
    case 'go-live-readiness':
      return <GoLiveReadinessView data={data} />
    case 'signoff-summary':
      return <SignoffSummaryView data={data} />
    case 'storage-usage':
      return <StorageUsageView data={data} />
    default:
      return null
  }
}

export default function ReportsPage() {
  const { slug } = useParams()
  const [cycles, setCycles] = useState([])
  const [cycleId, setCycleId] = useState('')
  const [reportType, setReportType] = useState('execution-summary')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  // Only used by the two comparison report types.
  const [suites, setSuites] = useState([])
  const [suiteId, setSuiteId] = useState('')
  const [revisions, setRevisions] = useState([])
  const [revisionAId, setRevisionAId] = useState('')
  const [revisionBId, setRevisionBId] = useState('')
  const [cycleBId, setCycleBId] = useState('')

  useEffect(() => {
    listCycles(slug, true).then((c) => {
      setCycles(c)
      if (c.length > 0) setCycleId(String(c[0].id))
    })
    listSuites(slug).then(setSuites)
  }, [slug])

  useEffect(() => {
    if (suiteId) listRevisions(slug, suiteId).then(setRevisions)
  }, [slug, suiteId])

  // Loads exactly the report the user selected, on demand — nothing is
  // pre-fetched for the other nine report types.
  const load = async () => {
    setLoading(true)
    setError(null)
    setData(null)
    try {
      let result
      switch (reportType) {
        case 'execution-summary':
          result = await getExecutionSummary(slug, cycleId)
          break
        case 'detailed-results':
          result = await getDetailedResults(slug, cycleId)
          break
        case 'ng-defects':
          result = await getNgDefects(slug, cycleId)
          break
        case 'evidence-completeness':
          result = await getEvidenceCompletenessReport(slug, cycleId)
          break
        case 'revision-comparison':
          result = await getRevisionComparison(slug, revisionAId, revisionBId)
          break
        case 'cycle-comparison':
          result = await getCycleComparison(slug, cycleId, cycleBId)
          break
        case 'tester-progress':
          result = await getTesterProgress(slug, cycleId)
          break
        case 'go-live-readiness':
          result = await getGoLiveReadinessReport(slug, cycleId)
          break
        case 'signoff-summary':
          result = await getSignoffSummary(slug, cycleId)
          break
        case 'storage-usage':
          result = await getStorageUsageReport(slug)
          break
        default:
          result = null
      }
      setData(result)
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not load this report')
    } finally {
      setLoading(false)
    }
  }

  const needsRevisionPicker = reportType === 'revision-comparison'
  const needsSecondCycle = reportType === 'cycle-comparison'
  const needsCycle = reportType !== 'storage-usage' && !needsRevisionPicker
  const meta = REPORT_META[reportType]

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h2 className="text-xl font-semibold text-gray-900">Reports</h2>
        {cycleId && (
          <div className="flex gap-2">
            <a href={exportExcelUrl(slug, cycleId)} className="px-3 py-1.5 text-sm border border-gray-300 rounded-md hover:bg-gray-50">
              Export Excel
            </a>
            <a href={exportZipUrl(slug, cycleId)} className="px-3 py-1.5 text-sm border border-gray-300 rounded-md hover:bg-gray-50">
              Export ZIP Package
            </a>
          </div>
        )}
      </div>

      <div className="bg-white border border-gray-200 rounded-lg p-5 flex flex-wrap gap-3 items-end">
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1">Report</label>
          <select
            value={reportType}
            onChange={(e) => {
              // Stale data from the previous report type must not be
              // rendered by the new type's (shape-specific) view -- each
              // view assumes the shape its own endpoint returns.
              setReportType(e.target.value)
              setData(null)
              setError(null)
            }}
            className="px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
          >
            {REPORT_TYPES.map((r) => (
              <option key={r.value} value={r.value}>
                {r.label}
              </option>
            ))}
          </select>
        </div>

        {needsCycle && (
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Cycle{needsSecondCycle ? ' A' : ''}</label>
            <select
              value={cycleId}
              onChange={(e) => setCycleId(e.target.value)}
              className="px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
            >
              {cycles.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>
        )}
        {needsSecondCycle && (
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Cycle B</label>
            <select
              value={cycleBId}
              onChange={(e) => setCycleBId(e.target.value)}
              className="px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
            >
              <option value="">Select…</option>
              {cycles.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>
        )}
        {needsRevisionPicker && (
          <>
            <div>
              <label className="block text-xs font-medium text-gray-500 mb-1">Suite</label>
              <select
                value={suiteId}
                onChange={(e) => setSuiteId(e.target.value)}
                className="px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
              >
                <option value="">Select…</option>
                {suites.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-500 mb-1">Revision A</label>
              <select
                value={revisionAId}
                onChange={(e) => setRevisionAId(e.target.value)}
                className="px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
              >
                <option value="">Select…</option>
                {revisions.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.revision_label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-500 mb-1">Revision B</label>
              <select
                value={revisionBId}
                onChange={(e) => setRevisionBId(e.target.value)}
                className="px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
              >
                <option value="">Select…</option>
                {revisions.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.revision_label}
                  </option>
                ))}
              </select>
            </div>
          </>
        )}

        <button onClick={load} className="px-4 py-2 bg-emerald-600 text-white text-sm font-medium rounded-md hover:bg-emerald-700">
          Run Report
        </button>
      </div>

      {meta && <p className="text-xs text-gray-500 -mt-3">{meta.description}</p>}

      {loading && <p className="text-sm text-gray-500">Loading…</p>}
      {error && <p className="text-sm text-red-600">{error}</p>}

      {data && (
        <div className="bg-white border border-gray-200 rounded-lg p-5">
          {renderReportBody(reportType, data)}
          <DeveloperData data={data} />
        </div>
      )}
    </div>
  )
}
