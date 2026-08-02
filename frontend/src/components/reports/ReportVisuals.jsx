import { useState } from 'react'
import StatusBadge from '../StatusBadge.jsx'

// Shared visual building blocks for ReportsPage.jsx (Track A reports
// only — HybridReportsPage.jsx is intentionally untouched and does not
// import from here). Replaces the old GenericTable/JSON.stringify
// fallback with purpose-built KPI cards, badges, progress bars, tables,
// timelines, and blocker lists, matching the conventions already
// established on Dashboard.jsx and StatusBadge.jsx.

const RESULT_TILE_LABELS = {
  NOT_RUN: 'Not Run',
  PASS: 'Pass',
  FAIL: 'NG',
  BLOCKED: 'Blocked',
  NOT_APPLICABLE: 'N/A',
}

export function KpiCard({ label, value, sub, formula }) {
  return (
    <div className="bg-white border border-gray-200 rounded-lg p-4" title={formula}>
      <p className="text-xs text-gray-500 uppercase">{label}</p>
      <p className="text-2xl font-semibold text-gray-900 mt-0.5">{value}</p>
      {sub && <p className="text-xs text-gray-400 mt-1">{sub}</p>}
    </div>
  )
}

export function ProgressStat({ label, percent, numerator, denominator, formula, danger }) {
  const pct = Math.min(Math.max(percent, 0), 100)
  return (
    <div className="bg-white border border-gray-200 rounded-lg p-5" title={formula}>
      <p className="text-xs font-medium text-gray-500 uppercase">{label}</p>
      <p className="text-3xl font-semibold text-gray-900 mt-1">{percent}%</p>
      <div className="w-full bg-gray-100 rounded-full h-2 mt-2">
        <div
          className={`h-2 rounded-full ${danger ? 'bg-red-500' : 'bg-emerald-500'}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <p className="text-xs text-gray-400 mt-2">
        {numerator} / {denominator} — {formula}
      </p>
    </div>
  )
}

export function ReadinessCard({ ready, blockers, formula }) {
  return (
    <div className="bg-white border border-gray-200 rounded-lg p-5">
      <div className="flex items-center gap-2">
        <p className="text-sm font-medium text-gray-900">Go-Live Readiness</p>
        <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${ready ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}`}>
          {ready ? 'READY' : 'NOT READY'}
        </span>
      </div>
      {blockers.length > 0 ? (
        <>
          <p className="text-xs font-medium text-gray-500 uppercase mt-3 mb-1">Blockers ({blockers.length})</p>
          <ul className="text-xs text-red-600 list-disc list-inside space-y-0.5">
            {blockers.map((b, i) => (
              <li key={i}>{b}</li>
            ))}
          </ul>
        </>
      ) : (
        <p className="text-xs text-emerald-600 mt-2">No blockers found.</p>
      )}
      <p className="text-xs text-gray-400 mt-3">{formula}</p>
    </div>
  )
}

export function ResultCountTiles({ counts }) {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
      {Object.entries(counts).map(([status, count]) => (
        <div key={status} className="bg-white border border-gray-200 rounded-lg p-4">
          <p className="text-xs text-gray-500 uppercase">{RESULT_TILE_LABELS[status] || status}</p>
          <p className="text-2xl font-semibold text-gray-900">{count}</p>
        </div>
      ))}
    </div>
  )
}

function cellValue(row, col) {
  const v = row[col]
  if (v === null || v === undefined || v === '') return <span className="text-gray-300">—</span>
  if (typeof v === 'boolean') return String(v)
  return v
}

// Status-like columns render as StatusBadge instead of plain text.
const BADGE_COLUMNS = new Set(['status', 'decision', 'severity', 'review_status'])

export function DataTable({ rows, emptyLabel = 'No rows.' }) {
  if (!rows || rows.length === 0) return <p className="text-xs text-gray-400">{emptyLabel}</p>
  const columns = Object.keys(rows[0])
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-gray-100 text-left text-gray-500 uppercase">
            {columns.map((c) => (
              <th key={c} className="px-3 py-2 whitespace-nowrap">
                {c.replace(/_/g, ' ')}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-b border-gray-50 hover:bg-gray-50">
              {columns.map((c) => (
                <td key={c} className="px-3 py-2 whitespace-nowrap max-w-xs truncate">
                  {BADGE_COLUMNS.has(c) && row[c] ? <StatusBadge status={row[c]} /> : cellValue(row, c)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function Timeline({ items, renderItem }) {
  if (!items || items.length === 0) return <p className="text-xs text-gray-400">No events recorded yet.</p>
  return (
    <ol className="relative border-l border-gray-200 ml-2 space-y-4">
      {items.map((item, i) => (
        <li key={i} className="ml-4">
          <div className="absolute w-2 h-2 bg-emerald-400 rounded-full -left-[4.5px] mt-1.5 border border-white" />
          {renderItem(item)}
        </li>
      ))}
    </ol>
  )
}

export function DiffColumn({ title, items, tone }) {
  const tones = {
    green: 'bg-green-100 text-green-700',
    red: 'bg-red-100 text-red-700',
    amber: 'bg-amber-100 text-amber-800',
    gray: 'bg-gray-100 text-gray-600',
  }
  return (
    <div>
      <p className="text-xs font-medium text-gray-500 uppercase mb-1">
        {title} ({items.length})
      </p>
      {items.length === 0 ? (
        <p className="text-xs text-gray-300">None</p>
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {items.map((cp) => (
            <span key={cp} className={`px-2 py-0.5 rounded text-xs font-mono ${tones[tone]}`}>
              {cp}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

export function BlockerList({ title, items, emptyLabel = 'None.' }) {
  return (
    <div>
      <p className="text-xs font-medium text-gray-500 uppercase mb-1">{title}</p>
      {!items || items.length === 0 ? (
        <p className="text-xs text-gray-400">{emptyLabel}</p>
      ) : (
        <ul className="text-xs text-red-600 list-disc list-inside space-y-0.5">
          {items.map((b, i) => (
            <li key={i} className="font-mono">
              {b}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

// Hidden by default — the raw API response, for anyone who needs to
// verify exact field values or debug a discrepancy against the visual
// summary above it. Never shown unless explicitly expanded.
export function DeveloperData({ data }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="mt-2">
      <button
        onClick={() => setOpen((o) => !o)}
        className="text-xs text-gray-400 hover:text-gray-600 underline decoration-dotted"
      >
        {open ? 'Hide Developer Data' : 'Show Developer Data'}
      </button>
      {open && (
        <pre className="mt-2 text-xs text-gray-700 whitespace-pre-wrap bg-gray-50 border border-gray-200 rounded-md p-3 max-h-96 overflow-auto">
          {JSON.stringify(data, null, 2)}
        </pre>
      )}
    </div>
  )
}
