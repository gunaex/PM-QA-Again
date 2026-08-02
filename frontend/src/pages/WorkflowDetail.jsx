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
  listWorkflowRuns,
  queueWorkflowRun,
  getWorkflowRun,
  cancelWorkflowRun,
  previewWorkflowRun,
} from '../api/client'
import { useAuth } from '../auth/AuthContext.jsx'
import StatusBadge from '../components/StatusBadge.jsx'
import RecordingPanel from '../components/RecordingPanel.jsx'
import CheckpointPanel from '../components/CheckpointPanel.jsx'
import RunResultBanner from '../components/RunResultBanner.jsx'
import { describeStep, STEP_RUN_ICON } from '../utils/describeStep.js'

const STEP_TYPES = [
  'NAVIGATE', 'CLICK', 'FILL', 'SELECT', 'CHECK', 'UNCHECK', 'PRESS_KEY',
  'WAIT_FOR_ELEMENT', 'WAIT', 'ASSERT_VISIBLE', 'ASSERT_TEXT', 'ASSERT_URL', 'SCREENSHOT', 'MANUAL_CHECKPOINT',
]
const LOCATOR_STRATEGIES = ['TEST_ID', 'ROLE', 'LABEL', 'PLACEHOLDER', 'TEXT', 'CSS', 'XPATH']
const LOCATOR_TYPES = new Set(['CLICK', 'FILL', 'SELECT', 'CHECK', 'UNCHECK', 'PRESS_KEY', 'WAIT_FOR_ELEMENT', 'ASSERT_VISIBLE'])
// Steps it makes sense to physically repeat in place -- excludes
// NAVIGATE/WAIT/WAIT_FOR_ELEMENT/MANUAL_CHECKPOINT/asserts, where
// "run this 5 times" either does nothing useful or is actively
// confusing (repeating a page-load, a pause, or an assertion).
const REPEATABLE_TYPES = new Set(['CLICK', 'FILL', 'SELECT', 'CHECK', 'UNCHECK', 'PRESS_KEY', 'SCREENSHOT'])

const emptyStepForm = {
  step_type: 'CLICK', locator_strategy: 'ROLE', locator_value: '', input_value: '', expected_value: '',
  is_sensitive: false, checkpoint_instructions: '', repeat_count: '',
}

// Raw runner/human event log -- useful for debugging a failure in
// detail, not for a first glance at "did it work" (that's
// RunResultBanner + the per-step icons above). Hidden by default,
// matching the "Show Developer Data" pattern already used on the
// redesigned Reports page (components/reports/ReportVisuals.jsx).
function DeveloperDataEvents({ events }) {
  const [open, setOpen] = useState(false)
  return (
    <div>
      <button onClick={() => setOpen((o) => !o)} className="text-xs text-gray-400 hover:text-gray-600 underline decoration-dotted">
        {open ? 'Hide Developer Data (event log)' : 'Show Developer Data (event log)'}
      </button>
      {open && (
        <ul className="mt-2 space-y-0.5 max-h-40 overflow-y-auto bg-gray-50 border border-gray-200 rounded-md p-2">
          {events.map((ev) => (
            <li key={ev.id} className="text-xs text-gray-500">
              <span className="font-mono">{ev.actor_type}</span> — {ev.event_type}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

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

  const [runs, setRuns] = useState([])
  const [expandedRunId, setExpandedRunId] = useState(null)
  const [expandedRunDetail, setExpandedRunDetail] = useState(null)
  const [repeatWholeTest, setRepeatWholeTest] = useState(1)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [startingRun, setStartingRun] = useState(false)

  const selectedRevision = revisions.find((r) => r.id === selectedRevisionId) || null
  const isDraft = selectedRevision?.status === 'DRAFT'
  const isPublished = selectedRevision?.status === 'PUBLISHED'

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

  const loadRuns = () => {
    listWorkflowRuns(slug).then((all) => {
      setRuns(all.filter((r) => revisions.some((rev) => rev.id === r.workflow_revision_id)))
    })
  }

  useEffect(() => {
    if (revisions.length === 0) return
    loadRuns()
    const interval = setInterval(loadRuns, 3000)
    return () => clearInterval(interval)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slug, revisions.length])

  useEffect(() => {
    if (!expandedRunId) {
      setExpandedRunDetail(null)
      return
    }
    const loadDetail = () => getWorkflowRun(slug, expandedRunId).then(setExpandedRunDetail)
    loadDetail()
    const interval = setInterval(loadDetail, 2000)
    return () => clearInterval(interval)
  }, [slug, expandedRunId])

  const handleQueueRun = async () => {
    // "Repeat whole test N×" is just N separate queued runs -- reuses
    // the exact same queue/claim/execute path a runner already
    // implements, no new mechanism.
    const times = Math.max(1, Number(repeatWholeTest) || 1)
    for (let i = 0; i < times; i++) {
      await queueWorkflowRun(slug, selectedRevisionId)
    }
    loadRuns()
  }

  const handleRunTest = async () => {
    if (!selectedRevisionId || startingRun) return
    setStartingRun(true)
    setError(null)
    try {
      const run = isPublished
        ? await queueWorkflowRun(slug, selectedRevisionId)
        : await previewWorkflowRun(slug, selectedRevisionId)
      setRuns((prev) => [run, ...prev.filter((item) => item.id !== run.id)])
      setExpandedRunId(run.id)
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not start this test')
    } finally {
      setStartingRun(false)
    }
  }

  const handleCancelRun = async (runId) => {
    await cancelWorkflowRun(slug, runId)
    loadRuns()
    if (expandedRunId === runId) getWorkflowRun(slug, runId).then(setExpandedRunDetail)
  }

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
      payload.repeat_count = REPEATABLE_TYPES.has(payload.step_type) && payload.repeat_count ? Number(payload.repeat_count) : null
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
        &larr; Automated Tests
      </NavLink>
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-2xl font-semibold text-gray-900">{workflow.name}</h2>
          <p className="text-sm text-gray-500 mt-1">Record actions. Run them again. Know whether the journey still works.</p>
        </div>
        <button
          onClick={() => setShowAdvanced((open) => !open)}
          className="text-xs text-gray-500 border border-gray-200 rounded-md px-3 py-1.5 hover:bg-white"
        >
          {showAdvanced ? 'Hide advanced' : 'Advanced'}
        </button>
      </div>
      {error && <p className="text-xs text-red-600">{error}</p>}

      <RecordingPanel
        slug={slug}
        workflowId={workflowId}
        canEdit={canEdit}
        nextRevisionLabel={`v${Math.max(0, ...revisions.map((revision) => revision.revision_number_sort || 0)) + 1}`}
        onDraftSaved={(revision) => {
          setRevisions((prev) => [revision, ...prev])
          setSelectedRevisionId(revision.id)
        }}
      />

      {selectedRevision && (
        <div className="bg-white border border-gray-200 rounded-xl overflow-hidden shadow-sm">
          <div className="px-5 py-4 border-b border-gray-100 flex items-center gap-3 flex-wrap">
            <div>
              <h3 className="font-semibold text-gray-900">Actions</h3>
              <p className="text-xs text-gray-500 mt-0.5">The journey QA-Again will replay in order.</p>
            </div>
            <span className="ml-auto text-xs text-gray-400">{steps.length} {steps.length === 1 ? 'action' : 'actions'}</span>
            {canEdit && steps.length > 0 && (
              <button
                onClick={handleRunTest}
                disabled={startingRun}
                className="px-4 py-2 bg-emerald-600 text-white text-sm font-medium rounded-md hover:bg-emerald-700 disabled:opacity-50"
              >
                {startingRun ? 'Starting…' : '▶ Run Test'}
              </button>
            )}
          </div>
          {steps.length === 0 ? (
            <div className="px-5 py-10 text-center">
              <p className="text-sm text-gray-500">No actions recorded yet.</p>
              <p className="text-xs text-gray-400 mt-1">Press Record above and use the website like a real tester.</p>
            </div>
          ) : (
            <ol className="divide-y divide-gray-100">
              {steps.map((step, index) => (
                <li key={step.id} className="px-5 py-3 flex items-center gap-3">
                  <span className="w-7 h-7 shrink-0 rounded-full bg-gray-100 text-gray-500 text-xs flex items-center justify-center">{index + 1}</span>
                  <span className="text-base" aria-hidden="true">{describeStep(step).icon}</span>
                  <span className="text-sm text-gray-800">{describeStep(step).text}</span>
                  {step.repeat_count > 1 && <span className="ml-auto text-xs text-gray-400">Repeat {step.repeat_count}×</span>}
                </li>
              ))}
            </ol>
          )}
        </div>
      )}

      {runs[0] && (
        <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
          <div className="p-5 flex items-center gap-4 flex-wrap">
            <div>
              <p className="text-xs font-medium text-gray-500 uppercase">Latest result</p>
              <div className="mt-2"><RunResultBanner status={runs[0].status} /></div>
            </div>
            <button
              onClick={() => setExpandedRunId((current) => current === runs[0].id ? null : runs[0].id)}
              className="ml-auto text-sm text-emerald-700 hover:underline"
            >
              {expandedRunId === runs[0].id ? 'Hide details' : 'View details'}
            </button>
          </div>
          {expandedRunId === runs[0].id && expandedRunDetail && (
            <div className="border-t border-gray-100 px-5 py-4">
              {(expandedRunDetail.step_runs || []).length === 0 ? (
                <p className="text-sm text-gray-500">The test is waiting to begin.</p>
              ) : (
                <ol className="space-y-2">
                  {expandedRunDetail.step_runs.map((stepRun) => (
                    <li key={stepRun.id} className="text-sm flex items-start gap-2">
                      <span>{STEP_RUN_ICON[stepRun.status] || '○'}</span>
                      <span className="text-gray-700">{describeStep(stepRun).text}</span>
                      {stepRun.machine_message && <span className="ml-auto text-xs text-red-600">{stepRun.machine_message}</span>}
                    </li>
                  ))}
                </ol>
              )}
            </div>
          )}
        </div>
      )}

      {showAdvanced && (
      <div className="grid grid-cols-1 lg:grid-cols-[240px_1fr] gap-4 border-t border-gray-200 pt-4">
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
                  Approve version
                </button>
              )}
              {canEdit && !isDraft && (
                <button onClick={handleClone} className="ml-auto px-3 py-1.5 text-sm border border-gray-300 rounded-md hover:bg-gray-50">
                  Create editable copy
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
                    <span title={`${s.step_type}${s.locator_value ? ` ${s.locator_strategy}=${s.locator_value}` : ''}`}>
                      {describeStep(s).icon} {describeStep(s).text}
                    </span>
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
                    {stepForm.step_type === 'WAIT' && (
                      <input
                        type="number"
                        min="1"
                        placeholder="Milliseconds (e.g. 2000)"
                        value={stepForm.input_value}
                        onChange={(e) => setStepForm({ ...stepForm, input_value: e.target.value })}
                        className="px-2 py-1 text-xs border border-gray-300 rounded w-40"
                      />
                    )}
                    {REPEATABLE_TYPES.has(stepForm.step_type) && (
                      <input
                        type="number"
                        min="2"
                        placeholder="Repeat ×N (optional)"
                        value={stepForm.repeat_count}
                        onChange={(e) => setStepForm({ ...stepForm, repeat_count: e.target.value })}
                        title="Re-execute this step N times in place before moving to the next step"
                        className="px-2 py-1 text-xs border border-gray-300 rounded w-32"
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

            {/* Runs (HYB-2) */}
            <div className="bg-white border border-gray-200 rounded-lg p-4">
              <div className="flex items-center gap-2 mb-2 flex-wrap">
                <p className="text-xs font-medium text-gray-500 uppercase">Runs ({runs.length})</p>
                {isPublished && canEdit && (
                  <span className="ml-auto flex items-center gap-2">
                    <label className="flex items-center gap-1 text-xs text-gray-500">
                      Repeat
                      <input
                        type="number"
                        min="1"
                        value={repeatWholeTest}
                        onChange={(e) => setRepeatWholeTest(e.target.value)}
                        title="Queue this same test N times"
                        className="w-12 px-1 py-0.5 border border-gray-300 rounded text-xs"
                      />
                      ×
                    </label>
                    <button onClick={handleQueueRun} className="px-3 py-1.5 text-xs bg-emerald-600 text-white rounded-md hover:bg-emerald-700">
                      Run published version
                    </button>
                  </span>
                )}
                {!isPublished && <p className="ml-auto text-xs text-gray-400">Publish a revision to queue a run.</p>}
              </div>
              {runs.length === 0 ? (
                <p className="text-xs text-gray-400">No runs yet.</p>
              ) : (
                <ul className="space-y-1">
                  {runs.map((r) => (
                    <li key={r.id} className="border border-gray-100 rounded">
                      <button
                        onClick={() => setExpandedRunId((prev) => (prev === r.id ? null : r.id))}
                        className="w-full flex items-center gap-2 px-2 py-1.5 text-xs text-left hover:bg-gray-50"
                      >
                        <span className="font-mono text-gray-400">#{r.id}</span>
                        <StatusBadge status={r.status} />
                        <span className="text-gray-500">{r.workflow_revision_label}</span>
                        {r.is_preview && (
                          <span
                            className="px-1.5 py-0.5 rounded bg-purple-100 text-purple-700"
                            title="Preview run -- not published, not counted in reports"
                          >
                            Preview
                          </span>
                        )}
                        {r.cancel_requested && <span className="text-amber-600">cancel requested</span>}
                        <span className="ml-auto text-gray-400">{expandedRunId === r.id ? '▲' : '▼'}</span>
                      </button>
                      {expandedRunId === r.id && expandedRunDetail && (
                        <div className="px-3 pb-3 pt-1 border-t border-gray-50 space-y-2">
                          <div className="flex items-center gap-2">
                            <RunResultBanner status={expandedRunDetail.status} />
                            {![
                              'PASSED', 'FAILED', 'BLOCKED', 'NOT_APPLICABLE', 'CANCELLED', 'RUNNER_LOST', 'SYSTEM_ERROR',
                            ].includes(expandedRunDetail.status) && (
                              <button onClick={() => handleCancelRun(r.id)} className="text-xs text-red-600 hover:underline ml-auto">
                                Cancel
                              </button>
                            )}
                          </div>
                          {(() => {
                            const checkpointStepRun = expandedRunDetail.step_runs.find((sr) => sr.step_type === 'MANUAL_CHECKPOINT')
                            if (!checkpointStepRun) return null
                            return (
                              <CheckpointPanel
                                slug={slug}
                                runId={r.id}
                                workflowStepId={checkpointStepRun.workflow_step_id}
                                run={expandedRunDetail}
                                canEdit={canEdit}
                                isAdmin={isAdmin}
                                onDecided={loadRuns}
                              />
                            )
                          })()}
                          <div>
                            <p className="text-[10px] font-medium text-gray-400 uppercase mb-1">Steps</p>
                            {expandedRunDetail.step_runs.length === 0 ? (
                              <p className="text-xs text-gray-400">No steps executed yet.</p>
                            ) : (
                              <ul className="space-y-0.5">
                                {expandedRunDetail.step_runs.map((sr) => (
                                  <li key={sr.id} className="text-xs flex items-center gap-2">
                                    <span className="font-mono text-gray-400 w-5">{sr.sequence_no}</span>
                                    <span>{STEP_RUN_ICON[sr.status] || '⚪'}</span>
                                    <span title={sr.step_type}>{describeStep(sr).text}</span>
                                    {sr.failure_category && <span className="text-red-600">{sr.failure_category}</span>}
                                    {sr.machine_message && <span className="text-gray-500 truncate max-w-xs">{sr.machine_message}</span>}
                                  </li>
                                ))}
                              </ul>
                            )}
                          </div>
                          <DeveloperDataEvents events={expandedRunDetail.events} />
                        </div>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        )}
      </div>
      )}
    </div>
  )
}
