import { useEffect, useRef, useState } from 'react'
import { NavLink, useNavigate, useParams } from 'react-router-dom'
import {
  getRevision,
  listCases,
  createCase,
  updateCase,
  deleteCase,
  publishRevision,
  cloneRevision,
  caseExportUrl,
  caseImportTemplateUrl,
  importCasesExcel,
  importCasesCsv,
} from '../api/client'
import { useAuth } from '../auth/AuthContext.jsx'
import StatusBadge from '../components/StatusBadge.jsx'

const MUTATION_LEVELS = ['UNSPECIFIED', 'READ_ONLY', 'MUTATING', 'MIXED']
const PRIORITIES = ['', 'P0', 'P1', 'P2', 'P3']

/** Suggests the next checkpoint code from the existing cases in this
 * revision -- editable afterward, never enforced server-side (the
 * backend still just requires uniqueness within the revision). Matches
 * the most common prefix already in use (e.g. "REG-P0-") and increments
 * its trailing number; falls back to "TC-001" for an empty revision. */
function suggestNextCheckpointCode(cases) {
  const matches = cases.map((c) => c.checkpoint_code?.match(/^(.*?)(\d+)$/)).filter(Boolean)
  if (matches.length === 0) return 'TC-001'
  const counts = {}
  for (const m of matches) counts[m[1]] = (counts[m[1]] || 0) + 1
  const prefix = Object.entries(counts).sort((a, b) => b[1] - a[1])[0][0]
  const width = matches.find((m) => m[1] === prefix)[2].length
  const maxNum = Math.max(...matches.filter((m) => m[1] === prefix).map((m) => parseInt(m[2], 10)))
  return `${prefix}${String(maxNum + 1).padStart(width, '0')}`
}

const emptyForm = {
  checkpoint_code: '',
  title: '',
  priority: '',
  traceability_md: '',
  setup_md: '',
  action_md: '',
  validation_md: '',
  expected_result_md: '',
  negative_path: false,
  mutation_level: 'UNSPECIFIED',
}

export default function RevisionDetail() {
  const { slug, suiteId, revisionId } = useParams()
  const { user } = useAuth()
  const isAdmin = user?.role === 'ADMIN'
  const canEdit = user?.role === 'ADMIN' || user?.role === 'TESTER'
  const navigate = useNavigate()
  const fileInputRef = useRef(null)

  const [revision, setRevision] = useState(null)
  const [cases, setCases] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [form, setForm] = useState(emptyForm)
  const [editingId, setEditingId] = useState(null)
  const [showForm, setShowForm] = useState(false)
  const [saving, setSaving] = useState(false)
  const [importMsg, setImportMsg] = useState(null)

  const isDraft = revision?.status === 'DRAFT'

  const load = () => {
    setLoading(true)
    setError(null)
    Promise.all([getRevision(slug, suiteId, revisionId), listCases(slug, revisionId)])
      .then(([r, c]) => {
        setRevision(r)
        setCases(c)
      })
      .catch(() => setError('Could not reach the backend.'))
      .finally(() => setLoading(false))
  }

  useEffect(load, [slug, suiteId, revisionId])

  const startEdit = (c) => {
    setEditingId(c.id)
    setForm({
      checkpoint_code: c.checkpoint_code,
      title: c.title,
      priority: c.priority || '',
      traceability_md: c.traceability_md || '',
      setup_md: c.setup_md || '',
      action_md: c.action_md,
      validation_md: c.validation_md || '',
      expected_result_md: c.expected_result_md,
      negative_path: c.negative_path,
      mutation_level: c.mutation_level,
    })
    setShowForm(true)
  }

  const resetForm = () => {
    setForm(emptyForm)
    setEditingId(null)
    setShowForm(false)
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    setSaving(true)
    setError(null)
    try {
      if (editingId) {
        const updated = await updateCase(slug, revisionId, editingId, form)
        setCases((prev) => prev.map((c) => (c.id === editingId ? updated : c)))
      } else {
        const created = await createCase(slug, revisionId, form)
        setCases((prev) => [...prev, created])
      }
      resetForm()
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not save the test case')
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (caseId) => {
    await deleteCase(slug, revisionId, caseId)
    setCases((prev) => prev.filter((c) => c.id !== caseId))
  }

  const handlePublish = async () => {
    if (!window.confirm('Publish this revision? Published content becomes immutable — corrections require cloning a new draft.')) return
    setError(null)
    try {
      const updated = await publishRevision(slug, suiteId, revisionId)
      setRevision(updated)
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not publish this revision')
    }
  }

  const handleClone = async () => {
    const label = window.prompt('New draft revision label for this correction:')
    if (!label) return
    const cloned = await cloneRevision(slug, suiteId, revisionId, { revision_label: label })
    navigate(`/${slug}/suites/${suiteId}/revisions/${cloned.id}`)
  }

  const handleImport = async (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    setImportMsg(null)
    setError(null)
    try {
      const isCsv = file.name.toLowerCase().endsWith('.csv')
      const result = isCsv ? await importCasesCsv(slug, revisionId, file) : await importCasesExcel(slug, revisionId, file)
      setImportMsg(
        `Imported ${result.imported} case(s).` +
          (result.duplicate_in_file.length ? ` Skipped duplicates in file: ${result.duplicate_in_file.join(', ')}.` : '') +
          (result.duplicate_existing.length ? ` Already existed: ${result.duplicate_existing.join(', ')}.` : ''),
      )
      load()
    } catch (err) {
      const detail = err.response?.data?.detail
      if (detail?.missing_columns) {
        setError(
          `Column headers don't match the template. Missing: ${detail.missing_columns.join(', ') || 'none'}. Unexpected: ${detail.unexpected_columns.join(', ') || 'none'}.`,
        )
      } else {
        setError(detail || 'Import failed')
      }
    } finally {
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  if (loading) return <p className="text-gray-500 text-sm">Loading…</p>
  if (error && !revision)
    return (
      <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded-md px-4 py-3">
        <p>{error}</p>
        <button onClick={load} className="mt-2 text-red-800 font-medium hover:underline">
          Retry
        </button>
      </div>
    )

  return (
    <div className="space-y-6">
      <div>
        <NavLink to={`/${slug}/suites/${suiteId}`} className="text-sm text-gray-500 hover:text-gray-800">
          &larr; Suite
        </NavLink>
        <div className="flex items-center gap-2 flex-wrap mt-1">
          <h2 className="text-xl font-semibold text-gray-900">{revision.revision_label}</h2>
          <StatusBadge status={revision.status} />
        </div>
        {revision.change_summary && <p className="text-sm text-gray-500 mt-1">{revision.change_summary}</p>}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <a
          href={caseExportUrl(slug, revisionId)}
          className="px-3 py-1.5 text-sm border border-gray-300 rounded-md hover:bg-gray-50"
        >
          Export Excel
        </a>
        {isDraft && canEdit && (
          <>
            <a
              href={caseImportTemplateUrl(slug, revisionId)}
              className="px-3 py-1.5 text-sm border border-gray-300 rounded-md hover:bg-gray-50"
            >
              Download Import Template
            </a>
            <label className="px-3 py-1.5 text-sm border border-gray-300 rounded-md hover:bg-gray-50 cursor-pointer">
              Import Excel/CSV
              <input ref={fileInputRef} type="file" accept=".xlsx,.csv" onChange={handleImport} className="hidden" />
            </label>
            <button
              onClick={() => {
                setForm({ ...emptyForm, checkpoint_code: suggestNextCheckpointCode(cases) })
                setEditingId(null)
                setShowForm(true)
              }}
              className="px-3 py-1.5 text-sm bg-emerald-600 text-white rounded-md hover:bg-emerald-700"
            >
              + Add Case
            </button>
          </>
        )}
        {isDraft && isAdmin && (
          <button
            onClick={handlePublish}
            disabled={cases.length === 0}
            className="px-3 py-1.5 text-sm bg-emerald-600 text-white rounded-md hover:bg-emerald-700 disabled:opacity-50"
          >
            Publish
          </button>
        )}
        {revision.status !== 'DRAFT' && canEdit && (
          <button onClick={handleClone} className="px-3 py-1.5 text-sm border border-gray-300 rounded-md hover:bg-gray-50">
            Clone for Correction
          </button>
        )}
      </div>

      {importMsg && <p className="text-xs text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-md px-3 py-2">{importMsg}</p>}
      {error && <p className="text-xs text-red-600 bg-red-50 border border-red-200 rounded-md px-3 py-2">{error}</p>}

      {showForm && (
        <form onSubmit={handleSubmit} className="bg-white border border-gray-200 rounded-lg p-5 space-y-3">
          <h3 className="font-medium text-gray-900">{editingId ? 'Edit test case' : 'New test case'}</h3>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <input
                required
                placeholder="Checkpoint code"
                value={form.checkpoint_code}
                onChange={(e) => setForm({ ...form, checkpoint_code: e.target.value })}
                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
              />
              {!editingId && <p className="text-[11px] text-gray-400 mt-0.5">Auto-suggested — change it if you need a specific code.</p>}
            </div>
            <input
              required
              placeholder="Title"
              value={form.title}
              onChange={(e) => setForm({ ...form, title: e.target.value })}
              className="px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
            />
            <select
              value={form.priority}
              onChange={(e) => setForm({ ...form, priority: e.target.value })}
              className="px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
            >
              {PRIORITIES.map((p) => (
                <option key={p} value={p}>
                  {p || 'Priority (not set)'}
                </option>
              ))}
            </select>
            <select
              value={form.mutation_level}
              onChange={(e) => setForm({ ...form, mutation_level: e.target.value })}
              className="px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
            >
              {MUTATION_LEVELS.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </div>
          <textarea
            placeholder="Traceability"
            value={form.traceability_md}
            onChange={(e) => setForm({ ...form, traceability_md: e.target.value })}
            className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
            rows={2}
          />
          <textarea
            placeholder="Setup / preconditions"
            value={form.setup_md}
            onChange={(e) => setForm({ ...form, setup_md: e.target.value })}
            className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
            rows={2}
          />
          <textarea
            required
            placeholder="Action / test steps"
            value={form.action_md}
            onChange={(e) => setForm({ ...form, action_md: e.target.value })}
            className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
            rows={3}
          />
          <textarea
            placeholder="Validation"
            value={form.validation_md}
            onChange={(e) => setForm({ ...form, validation_md: e.target.value })}
            className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
            rows={2}
          />
          <textarea
            required
            placeholder="Expected result"
            value={form.expected_result_md}
            onChange={(e) => setForm({ ...form, expected_result_md: e.target.value })}
            className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
            rows={2}
          />
          <label className="flex items-center gap-2 text-sm text-gray-600">
            <input
              type="checkbox"
              checked={form.negative_path}
              onChange={(e) => setForm({ ...form, negative_path: e.target.checked })}
            />
            Negative path
          </label>
          <div className="flex gap-2">
            <button
              type="submit"
              disabled={saving}
              className="px-4 py-2 bg-emerald-600 text-white text-sm font-medium rounded-md hover:bg-emerald-700 disabled:opacity-50"
            >
              {saving ? 'Saving…' : editingId ? 'Save changes' : 'Add case'}
            </button>
            <button
              type="button"
              onClick={resetForm}
              className="px-4 py-2 text-sm text-gray-600 border border-gray-200 rounded-md hover:bg-gray-50"
            >
              Cancel
            </button>
          </div>
        </form>
      )}

      {cases.length === 0 ? (
        <p className="text-gray-500 text-sm">No test cases yet.</p>
      ) : (
        <div className="bg-white border border-gray-200 rounded-lg overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 text-left text-xs text-gray-500 uppercase tracking-wide">
                <th className="px-4 py-2">Checkpoint</th>
                <th className="px-4 py-2">Title</th>
                <th className="px-4 py-2">Priority</th>
                <th className="px-4 py-2">Mutation</th>
                {isDraft && canEdit && <th className="px-4 py-2"></th>}
              </tr>
            </thead>
            <tbody>
              {cases.map((c) => (
                <tr key={c.id} className="border-b border-gray-50 last:border-0">
                  <td className="px-4 py-2 font-mono text-xs text-gray-700">{c.checkpoint_code}</td>
                  <td className="px-4 py-2 text-gray-900">{c.title}</td>
                  <td className="px-4 py-2 text-gray-500">{c.priority || '—'}</td>
                  <td className="px-4 py-2 text-gray-500">{c.mutation_level}</td>
                  {isDraft && canEdit && (
                    <td className="px-4 py-2 text-right whitespace-nowrap">
                      <button onClick={() => startEdit(c)} className="text-xs text-emerald-600 hover:underline mr-3">
                        Edit
                      </button>
                      <button onClick={() => handleDelete(c.id)} className="text-xs text-red-500 hover:underline">
                        Delete
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
