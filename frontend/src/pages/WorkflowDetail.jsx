import { useEffect, useState } from 'react'
import { NavLink, useParams } from 'react-router-dom'
import {
  getWorkflow,
  listWorkflowRevisions,
  createWorkflowRevision,
  publishWorkflowRevision,
  cloneWorkflowRevision,
  listWorkflowSteps,
  createWorkflowStep,
  deleteWorkflowStep,
  reorderWorkflowSteps,
  listWorkflowLinks,
  createWorkflowLink,
  deleteWorkflowLink,
  listSuites,
  listRevisions,
  listCases,
} from '../api/client'
import { useAuth } from '../auth/AuthContext.jsx'
import StatusBadge from '../components/StatusBadge.jsx'

const STEP_TYPES = [
  'NAVIGATE', 'CLICK', 'FILL', 'SELECT', 'CHECK', 'UNCHECK', 'PRESS_KEY',
  'WAIT_FOR_ELEMENT', 'ASSERT_VISIBLE', 'ASSERT_TEXT', 'ASSERT_URL', 'SCREENSHOT', 'MANUAL_CHECKPOINT',
]
const LOCATOR_STRATEGIES = ['TEST_ID', 'ROLE', 'LABEL', 'PLACEHOLDER', 'TEXT', 'CSS', 'XPATH']
const LOCATOR_TYPES = new Set(['CLICK', 'FILL', 'SELECT', 'CHECK', 'UNCHECK', 'PRESS_KEY', 'WAIT_FOR_ELEMENT', 'ASSERT_VISIBLE'])

const emptyStepForm = { step_type: 'CLICK', locator_strategy: 'ROLE', locator_value: '', input_value: '', expected_value: '', is_sensitive: false, checkpoint_instructions: '' }

export default function WorkflowDetail() {
  const { slug, workflowId } = useParams()
  const { user } = useAuth()
  const canEdit = user?.role === 'ADMIN' || user?.role === 'TESTER'
  const isAdmin = user?.role === 'ADMIN'

  const [workflow, setWorkflow] = useState(null)
  const [revisions, setRevisions] = useState([])
  const [selectedRevisionId, setSelectedRevisionId] = useState(null)
  const [steps, setSteps] = useState([])
  const [links, setLinks] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const [newRevisionLabel, setNewRevisionLabel] = useState('')
  const [stepForm, setStepForm] = useState(emptyStepForm)

  const [linkSuites, setLinkSuites] = useState([])
  const [linkSuiteId, setLinkSuiteId] = useState('')
  const [linkRevisions, setLinkRevisions] = useState([])
  const [linkRevisionId, setLinkRevisionId] = useState('')
  const [linkCases, setLinkCases] = useState([])
  const [linkCaseId, setLinkCaseId] = useState('')

  const selectedRevision = revisions.find((r) => r.id === selectedRevisionId) || null
  const isDraft = selectedRevision?.status === 'DRAFT'

  const load = () => {
    setLoading(true)
    setError(null)
    Promise.all([getWorkflow(slug, workflowId), listWorkflowRevisions(slug, workflowId)])
      .then(([w, revs]) => {
        setWorkflow(w)
        setRevisions(revs)
        setSelectedRevisionId((prev) => prev ?? revs[0]?.id ?? null)
      })
      .catch(() => setError('Could not reach the backend.'))
      .finally(() => setLoading(false))
  }

  useEffect(load, [slug, workflowId])

  useEffect(() => {
    if (!selectedRevisionId) {
      setSteps([])
      setLinks([])
      return
    }
    listWorkflowSteps(slug, workflowId, selectedRevisionId).then(setSteps)
    listWorkflowLinks(slug, workflowId, selectedRevisionId).then(setLinks)
  }, [slug, workflowId, selectedRevisionId])

  useEffect(() => {
    listSuites(slug).then(setLinkSuites)
  }, [slug])

  const handleCreateRevision = async (e) => {
    e.preventDefault()
    if (!newRevisionLabel.trim()) return
    const rev = await createWorkflowRevision(slug, workflowId, { revision_label: newRevisionLabel.trim() })
    setNewRevisionLabel('')
    setRevisions((prev) => [rev, ...prev])
    setSelectedRevisionId(rev.id)
  }

  const handlePublish = async () => {
    const updated = await publishWorkflowRevision(slug, workflowId, selectedRevisionId)
    setRevisions((prev) => prev.map((r) => (r.id === updated.id ? updated : r)))
  }

  const handleClone = async () => {
    const label = window.prompt('New draft revision label (e.g. v2):')
    if (!label) return
    const clone = await cloneWorkflowRevision(slug, workflowId, selectedRevisionId, { revision_label: label })
    setRevisions((prev) => [clone, ...prev])
    setSelectedRevisionId(clone.id)
  }

  const handleAddStep = async (e) => {
    e.preventDefault()
    setError(null)
    try {
      const payload = { ...stepForm }
      if (!LOCATOR_TYPES.has(payload.step_type)) {
        payload.locator_strategy = null
        payload.locator_value = null
      }
      const step = await createWorkflowStep(slug, workflowId, selectedRevisionId, payload)
      setSteps((prev) => [...prev, step])
      setStepForm(emptyStepForm)
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not add step')
    }
  }

  const handleDeleteStep = async (stepId) => {
    await deleteWorkflowStep(slug, workflowId, selectedRevisionId, stepId)
    setSteps((prev) => prev.filter((s) => s.id !== stepId))
  }

  const moveStep = async (index, direction) => {
    const newIndex = index + direction
    if (newIndex < 0 || newIndex >= steps.length) return
    const reordered = [...steps]
    ;[reordered[index], reordered[newIndex]] = [reordered[newIndex], reordered[index]]
    const ids = reordered.map((s) => s.id)
    const updated = await reorderWorkflowSteps(slug, workflowId, selectedRevisionId, ids)
    setSteps(updated)
  }

  const onLinkSuiteChange = async (suiteId) => {
    setLinkSuiteId(suiteId)
    setLinkRevisionId('')
    setLinkCases([])
    if (!suiteId) {
      setLinkRevisions([])
      return
    }
    const revs = await listRevisions(slug, suiteId)
    setLinkRevisions(revs)
  }

  const onLinkRevisionChange = async (revisionId) => {
    setLinkRevisionId(revisionId)
    if (!revisionId) {
      setLinkCases([])
      return
    }
    const cases = await listCases(slug, revisionId)
    setLinkCases(cases)
  }

  const handleAddLink = async (e) => {
    e.preventDefault()
    if (!linkCaseId) return
    const link = await createWorkflowLink(slug, workflowId, selectedRevisionId, Number(linkCaseId))
    setLinks((prev) => [...prev, link])
    setLinkCaseId('')
  }

  const handleDeleteLink = async (linkId) => {
    await deleteWorkflowLink(slug, workflowId, selectedRevisionId, linkId)
    setLinks((prev) => prev.filter((l) => l.id !== linkId))
  }

  if (loading) return <p className="text-gray-500 text-sm">Loading…</p>
  if (error && !workflow)
    return (
      <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded-md px-4 py-3">
        <p>{error}</p>
        <button onClick={load} className="mt-2 text-red-800 font-medium hover:underline">
          Retry
        </button>
      </div>
    )

  return (
    <div className="space-y-4">
      <NavLink to={`/${slug}/workflows`} className="text-sm text-gray-500 hover:text-gray-800">
        &larr; Workflows
      </NavLink>
      <h2 className="text-xl font-semibold text-gray-900">{workflow.name}</h2>
      {error && <p className="text-xs text-red-600">{error}</p>}

      <div className="grid grid-cols-1 lg:grid-cols-[240px_1fr] gap-4">
        {/* Revision list */}
        <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
          {canEdit && (
            <form onSubmit={handleCreateRevision} className="p-2 border-b border-gray-100 flex gap-1">
              <input
                value={newRevisionLabel}
                onChange={(e) => setNewRevisionLabel(e.target.value)}
                placeholder="Revision label (e.g. v1)"
                className="flex-1 px-2 py-1 text-xs border border-gray-300 rounded"
              />
              <button type="submit" className="px-2 py-1 text-xs bg-emerald-600 text-white rounded">
                New Draft Revision
              </button>
            </form>
          )}
          <div className="divide-y divide-gray-50">
            {revisions.map((r) => (
              <button
                key={r.id}
                onClick={() => setSelectedRevisionId(r.id)}
                className={`w-full text-left px-3 py-2 text-xs hover:bg-gray-50 ${selectedRevisionId === r.id ? 'bg-emerald-50' : ''}`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono">{r.revision_label}</span>
                  <StatusBadge status={r.status} />
                </div>
              </button>
            ))}
          </div>
        </div>

        {/* Revision detail: steps + links */}
        {selectedRevision && (
          <div className="space-y-4">
            <div className="bg-white border border-gray-200 rounded-lg p-4 flex items-center gap-2 flex-wrap">
              <span className="font-mono text-sm">{selectedRevision.revision_label}</span>
              <StatusBadge status={selectedRevision.status} />
              {isAdmin && isDraft && (
                <button onClick={handlePublish} className="ml-auto px-3 py-1.5 text-sm bg-emerald-600 text-white rounded-md hover:bg-emerald-700">
                  Publish
                </button>
              )}
              {canEdit && !isDraft && (
                <button onClick={handleClone} className="ml-auto px-3 py-1.5 text-sm border border-gray-300 rounded-md hover:bg-gray-50">
                  Clone for correction
                </button>
              )}
            </div>

            {/* Steps */}
            <div className="bg-white border border-gray-200 rounded-lg p-4">
              <p className="text-xs font-medium text-gray-500 uppercase mb-2">Steps ({steps.length})</p>
              <ol className="space-y-1 mb-3">
                {steps.map((s, i) => (
                  <li key={s.id} className="flex items-center gap-2 text-xs border border-gray-100 rounded px-2 py-1.5">
                    <span className="font-mono text-gray-400 w-5">{i + 1}</span>
                    <span className="px-1.5 py-0.5 rounded bg-gray-100 font-medium">{s.step_type}</span>
                    {s.locator_value && <span className="text-gray-500">{s.locator_strategy}={s.locator_value}</span>}
                    {s.input_value && <span className="text-gray-500">value: {s.is_sensitive ? s.input_value : s.input_value}</span>}
                    {s.checkpoint_instructions && <span className="text-amber-700">checkpoint: {s.checkpoint_instructions}</span>}
                    {isDraft && canEdit && (
                      <span className="ml-auto flex gap-1">
                        <button onClick={() => moveStep(i, -1)} disabled={i === 0} className="px-1 border rounded disabled:opacity-30">
                          ↑
                        </button>
                        <button onClick={() => moveStep(i, 1)} disabled={i === steps.length - 1} className="px-1 border rounded disabled:opacity-30">
                          ↓
                        </button>
                        <button onClick={() => handleDeleteStep(s.id)} className="px-1 border rounded text-red-600">
                          ✕
                        </button>
                      </span>
                    )}
                  </li>
                ))}
              </ol>

              {isDraft && canEdit && (
                <form onSubmit={handleAddStep} className="border-t border-gray-100 pt-3 space-y-2">
                  <div className="flex gap-2 flex-wrap">
                    <select
                      value={stepForm.step_type}
                      onChange={(e) => setStepForm({ ...stepForm, step_type: e.target.value })}
                      className="px-2 py-1 text-xs border border-gray-300 rounded"
                    >
                      {STEP_TYPES.map((t) => (
                        <option key={t} value={t}>
                          {t}
                        </option>
                      ))}
                    </select>
                    {LOCATOR_TYPES.has(stepForm.step_type) && (
                      <>
                        <select
                          value={stepForm.locator_strategy}
                          onChange={(e) => setStepForm({ ...stepForm, locator_strategy: e.target.value })}
                          className="px-2 py-1 text-xs border border-gray-300 rounded"
                        >
                          {LOCATOR_STRATEGIES.map((s) => (
                            <option key={s} value={s}>
                              {s}
                            </option>
                          ))}
                        </select>
                        <input
                          placeholder="Locator value"
                          value={stepForm.locator_value}
                          onChange={(e) => setStepForm({ ...stepForm, locator_value: e.target.value })}
                          className="px-2 py-1 text-xs border border-gray-300 rounded flex-1 min-w-[140px]"
                        />
                      </>
                    )}
                    {['NAVIGATE', 'FILL', 'SELECT', 'PRESS_KEY'].includes(stepForm.step_type) && (
                      <input
                        placeholder={stepForm.is_sensitive ? '${SECRET_VAR_NAME}' : 'Input value'}
                        value={stepForm.input_value}
                        onChange={(e) => setStepForm({ ...stepForm, input_value: e.target.value })}
                        className="px-2 py-1 text-xs border border-gray-300 rounded flex-1 min-w-[140px]"
                      />
                    )}
                    {['ASSERT_TEXT', 'ASSERT_URL'].includes(stepForm.step_type) && (
                      <input
                        placeholder="Expected value"
                        value={stepForm.expected_value}
                        onChange={(e) => setStepForm({ ...stepForm, expected_value: e.target.value })}
                        className="px-2 py-1 text-xs border border-gray-300 rounded flex-1 min-w-[140px]"
                      />
                    )}
                    {stepForm.step_type === 'MANUAL_CHECKPOINT' && (
                      <input
                        placeholder="Checkpoint instructions for the human tester"
                        value={stepForm.checkpoint_instructions}
                        onChange={(e) => setStepForm({ ...stepForm, checkpoint_instructions: e.target.value })}
                        className="px-2 py-1 text-xs border border-gray-300 rounded flex-1 min-w-[200px]"
                      />
                    )}
                    {['FILL', 'SELECT'].includes(stepForm.step_type) && (
                      <label className="flex items-center gap-1 text-xs text-gray-600">
                        <input
                          type="checkbox"
                          checked={stepForm.is_sensitive}
                          onChange={(e) => setStepForm({ ...stepForm, is_sensitive: e.target.checked })}
                        />
                        Sensitive (use a ${'{'}VAR{'}'} placeholder, never a real value)
                      </label>
                    )}
                  </div>
                  <button type="submit" className="px-3 py-1.5 text-xs bg-gray-800 text-white rounded-md hover:bg-gray-900">
                    + Add Step
                  </button>
                </form>
              )}
            </div>

            {/* Test case links */}
            <div className="bg-white border border-gray-200 rounded-lg p-4">
              <p className="text-xs font-medium text-gray-500 uppercase mb-2">Linked Test Cases ({links.length})</p>
              <ul className="space-y-1 mb-3">
                {links.map((l) => (
                  <li key={l.id} className="flex items-center gap-2 text-xs border border-gray-100 rounded px-2 py-1.5">
                    <span className="font-mono text-gray-500">{l.checkpoint_code}</span>
                    <span>{l.case_title}</span>
                    {isDraft && canEdit && (
                      <button onClick={() => handleDeleteLink(l.id)} className="ml-auto px-1 border rounded text-red-600">
                        ✕
                      </button>
                    )}
                  </li>
                ))}
              </ul>
              {isDraft && canEdit && (
                <form onSubmit={handleAddLink} className="flex gap-2 flex-wrap">
                  <select value={linkSuiteId} onChange={(e) => onLinkSuiteChange(e.target.value)} className="px-2 py-1 text-xs border border-gray-300 rounded">
                    <option value="">Select suite…</option>
                    {linkSuites.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.name}
                      </option>
                    ))}
                  </select>
                  <select
                    value={linkRevisionId}
                    onChange={(e) => onLinkRevisionChange(e.target.value)}
                    disabled={!linkSuiteId}
                    className="px-2 py-1 text-xs border border-gray-300 rounded disabled:opacity-50"
                  >
                    <option value="">Select revision…</option>
                    {linkRevisions.map((r) => (
                      <option key={r.id} value={r.id}>
                        {r.revision_label} ({r.status})
                      </option>
                    ))}
                  </select>
                  <select
                    value={linkCaseId}
                    onChange={(e) => setLinkCaseId(e.target.value)}
                    disabled={!linkRevisionId}
                    className="px-2 py-1 text-xs border border-gray-300 rounded disabled:opacity-50"
                  >
                    <option value="">Select case…</option>
                    {linkCases.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.checkpoint_code} — {c.title}
                      </option>
                    ))}
                  </select>
                  <button type="submit" className="px-3 py-1.5 text-xs bg-gray-800 text-white rounded-md hover:bg-gray-900">
                    + Link Case
                  </button>
                </form>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
