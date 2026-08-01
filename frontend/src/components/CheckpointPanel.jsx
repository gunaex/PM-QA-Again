import { useEffect, useState } from 'react'
import {
  getCheckpointContext,
  submitCheckpointDecision,
  reviewCheckpointDecision,
  listDefects,
  createDefect,
  updateDefect,
} from '../api/client'
import { useAuth } from '../auth/AuthContext.jsx'
import StatusBadge from './StatusBadge.jsx'
import EvidenceGallery from './EvidenceGallery.jsx'

const DECISION_STATUSES = ['PASS', 'FAIL', 'BLOCKED', 'NOT_APPLICABLE']

function formatElapsed(seconds) {
  if (seconds == null) return null
  const s = Math.floor(seconds)
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  const rem = s % 60
  if (m < 60) return `${m}m ${rem}s`
  const h = Math.floor(m / 60)
  return `${h}h ${m % 60}m`
}

/** HYB-4: the human checkpoint review panel. Rendered inline under a
 * WorkflowRun's expanded detail (WorkflowDetail.jsx) whenever that run
 * is WAITING_FOR_HUMAN, or to show the already-decided history
 * otherwise. Reuses EvidenceGallery/AnnotationEditor for screenshots and
 * annotation (never a parallel evidence viewer), and the existing
 * defect create/update endpoints for linkage -- no parallel subsystem. */
export default function CheckpointPanel({ slug, runId, workflowStepId, run, canEdit, isAdmin, onDecided }) {
  const { user } = useAuth()
  const [ctx, setCtx] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [status, setStatus] = useState('PASS')
  const [actualResult, setActualResult] = useState('')
  const [reason, setReason] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [evidenceIds, setEvidenceIds] = useState([])
  const [defects, setDefects] = useState([])
  const [defectTitle, setDefectTitle] = useState('')
  const [linkDefectId, setLinkDefectId] = useState('')

  const isWaiting = run?.status === 'WAITING_FOR_HUMAN'

  const load = () => {
    getCheckpointContext(slug, runId, workflowStepId)
      .then(setCtx)
      .catch(() => setError('Could not load checkpoint context'))
      .finally(() => setLoading(false))
  }

  useEffect(load, [slug, runId, workflowStepId])

  // Live-poll while waiting -- shows elapsed time ticking and picks up a
  // decision made from a different browser tab/session.
  useEffect(() => {
    if (!isWaiting) return
    const interval = setInterval(load, 3000)
    return () => clearInterval(interval)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isWaiting, slug, runId, workflowStepId])

  const resultId = run?.cycle_test_result_id ?? null
  // The checkpoint step's own step-run id, if the runner has created one
  // (it does so before posting CHECKPOINT_WAITING -- see runner/src/
  // execution/executor.ts).
  const checkpointStepRun = ctx?.run?.step_runs?.find((sr) => sr.workflow_step_id === workflowStepId)

  useEffect(() => {
    if (!resultId || !ctx?.cycle_id) return
    listDefects(slug, ctx.cycle_id).then(setDefects).catch(() => {})
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slug, resultId, ctx?.cycle_id])

  const handleSubmit = async () => {
    setSubmitting(true)
    setError(null)
    try {
      const decision = await submitCheckpointDecision(slug, runId, {
        workflow_step_id: workflowStepId,
        status,
        actual_result_md: actualResult || null,
        reason: reason || null,
        evidence_ids: evidenceIds,
        idempotency_key: `${runId}-${workflowStepId}-${Date.now()}`,
      })
      setActualResult('')
      setReason('')
      setEvidenceIds([])
      load()
      onDecided?.(decision)
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not submit decision')
    } finally {
      setSubmitting(false)
    }
  }

  const handleReview = async (decisionId, reviewStatus) => {
    await reviewCheckpointDecision(slug, runId, decisionId, reviewStatus)
    load()
  }

  const handleCreateDefect = async () => {
    if (!defectTitle.trim()) return
    const defect = await createDefect(slug, {
      title: defectTitle.trim(),
      cycle_id: ctx?.cycle_id ?? null,
      cycle_test_result_id: resultId,
      severity: 'UNSPECIFIED',
      workflow_run_id: runId,
      workflow_step_run_id: checkpointStepRun?.id ?? null,
    })
    setDefects((prev) => [defect, ...prev])
    setDefectTitle('')
  }

  const handleLinkDefect = async () => {
    if (!linkDefectId) return
    const updated = await updateDefect(slug, Number(linkDefectId), {
      workflow_run_id: runId,
      workflow_step_run_id: checkpointStepRun?.id ?? null,
    })
    setDefects((prev) => prev.map((d) => (d.id === updated.id ? updated : d)))
    setLinkDefectId('')
  }

  if (loading) return <p className="text-xs text-gray-400">Loading checkpoint…</p>
  if (!ctx) return <p className="text-xs text-red-600">Could not load checkpoint.</p>

  const elapsed = formatElapsed(ctx.elapsed_waiting_seconds)
  const linkedDefects = defects.filter((d) => d.workflow_run_id === runId)

  return (
    <div className="border border-amber-200 bg-amber-50 rounded-md p-3 space-y-3">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-xs font-semibold text-amber-800 uppercase">Manual Checkpoint</span>
        {isWaiting && <StatusBadge status="WAITING_FOR_HUMAN" />}
        {elapsed && isWaiting && <span className="text-xs text-amber-700">waiting {elapsed}</span>}
        <span className="ml-auto text-xs text-gray-500">
          {ctx.workflow_name} — {ctx.workflow_revision_label}
        </span>
      </div>

      {ctx.checkpoint_instructions && (
        <div>
          <p className="text-[10px] font-medium text-gray-500 uppercase">Instructions</p>
          <p className="text-sm text-gray-800 whitespace-pre-wrap">{ctx.checkpoint_instructions}</p>
        </div>
      )}
      {ctx.expected_value && (
        <div>
          <p className="text-[10px] font-medium text-gray-500 uppercase">Expected Result</p>
          <p className="text-sm text-gray-800 whitespace-pre-wrap">{ctx.expected_value}</p>
        </div>
      )}

      {ctx.linked_test_cases.length > 0 && (
        <div>
          <p className="text-[10px] font-medium text-gray-500 uppercase">Linked Track A Test Case(s)</p>
          <ul className="text-xs text-gray-700">
            {ctx.linked_test_cases.map((l) => (
              <li key={l.id}>
                <span className="font-mono text-gray-500">{l.checkpoint_code}</span> — {l.case_title}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div>
        <p className="text-[10px] font-medium text-gray-500 uppercase mb-1">Prior Automated Step Results</p>
        {ctx.run.step_runs.length === 0 ? (
          <p className="text-xs text-gray-400">None yet.</p>
        ) : (
          <ul className="space-y-0.5">
            {ctx.run.step_runs.map((sr) => (
              <li key={sr.id} className="text-xs flex items-center gap-2">
                <span className="font-mono text-gray-400 w-5">{sr.sequence_no}</span>
                <span className="px-1 rounded bg-gray-100">{sr.step_type}</span>
                <StatusBadge status={sr.status} />
                {sr.machine_message && <span className="text-gray-500 truncate max-w-xs">{sr.machine_message}</span>}
              </li>
            ))}
          </ul>
        )}
      </div>

      {resultId && ctx.cycle_id && (
        <EvidenceGallery
          slug={slug}
          cycleId={ctx.cycle_id}
          resultId={resultId}
          canEdit={canEdit}
          isAdmin={isAdmin}
          isLocked={false}
          workflowRunId={runId}
          workflowStepRunId={checkpointStepRun?.id ?? null}
        />
      )}
      {!resultId && <p className="text-xs text-gray-400">This run has no linked Track A result — no evidence gallery available.</p>}

      <div>
        <p className="text-[10px] font-medium text-gray-500 uppercase mb-1">Defects</p>
        {linkedDefects.length === 0 ? (
          <p className="text-xs text-gray-400 mb-1">None linked yet.</p>
        ) : (
          <ul className="text-xs mb-1">
            {linkedDefects.map((d) => (
              <li key={d.id}>
                <span className="font-mono text-gray-500">{d.defect_key}</span> {d.title} <StatusBadge status={d.status} />
              </li>
            ))}
          </ul>
        )}
        {canEdit && resultId && (
          <div className="flex gap-2 flex-wrap">
            <input
              value={defectTitle}
              onChange={(e) => setDefectTitle(e.target.value)}
              placeholder="New defect title"
              className="px-2 py-1 text-xs border border-gray-300 rounded flex-1 min-w-[160px]"
            />
            <button onClick={handleCreateDefect} className="px-2 py-1 text-xs bg-gray-800 text-white rounded">
              + Create Defect
            </button>
            <input
              value={linkDefectId}
              onChange={(e) => setLinkDefectId(e.target.value)}
              placeholder="Existing defect ID"
              className="px-2 py-1 text-xs border border-gray-300 rounded w-32"
            />
            <button onClick={handleLinkDefect} className="px-2 py-1 text-xs border border-gray-300 rounded">
              Link
            </button>
          </div>
        )}
      </div>

      <div>
        <p className="text-[10px] font-medium text-gray-500 uppercase mb-1">Decision History</p>
        {ctx.decisions.length === 0 ? (
          <p className="text-xs text-gray-400">No decision yet.</p>
        ) : (
          <ul className="space-y-1">
            {ctx.decisions.map((d) => (
              <li key={d.id} className="text-xs border-l-2 border-gray-200 pl-2">
                <span className="font-medium">rev {d.decision_revision_no}</span> — <StatusBadge status={d.status} /> by{' '}
                {d.decided_by_email} at {new Date(d.decided_at).toLocaleString()} (source: {d.source})
                {d.actual_result_md && <div className="text-gray-600 mt-0.5">{d.actual_result_md}</div>}
                {d.reason && <div className="text-gray-600 mt-0.5">Reason: {d.reason}</div>}
                {d.status === 'NOT_APPLICABLE' && (
                  <div className="mt-1 flex items-center gap-2">
                    <span className="text-gray-500">Admin review:</span>
                    <StatusBadge status={d.review_status || 'UNREVIEWED'} />
                    {isAdmin && d.review_status === 'UNREVIEWED' && (
                      <>
                        <button onClick={() => handleReview(d.id, 'ACCEPTED')} className="text-emerald-600 hover:underline">
                          Accept
                        </button>
                        <button onClick={() => handleReview(d.id, 'CHANGES_REQUESTED')} className="text-red-500 hover:underline">
                          Request changes
                        </button>
                      </>
                    )}
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>

      {error && <p className="text-xs text-red-700 bg-red-50 border border-red-200 rounded px-2 py-1">{error}</p>}

      {isWaiting && canEdit && (
        <div className="border-t border-amber-200 pt-3 space-y-2">
          <p className="text-[10px] font-medium text-gray-500 uppercase">Your Decision (as {user?.email})</p>
          <div className="flex gap-2 flex-wrap">
            {DECISION_STATUSES.map((s) => (
              <button
                key={s}
                onClick={() => setStatus(s)}
                className={`px-2 py-1 text-xs rounded border ${
                  status === s ? 'bg-gray-800 text-white border-gray-800' : 'border-gray-300 text-gray-600 hover:bg-gray-50'
                }`}
              >
                {s}
              </button>
            ))}
          </div>
          <textarea
            value={actualResult}
            onChange={(e) => setActualResult(e.target.value)}
            placeholder="Actual result (required for FAIL)"
            rows={2}
            className="w-full px-2 py-1 text-xs border border-gray-300 rounded"
          />
          <input
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Reason (required for BLOCKED / NOT_APPLICABLE)"
            className="w-full px-2 py-1 text-xs border border-gray-300 rounded"
          />
          <button
            onClick={handleSubmit}
            disabled={submitting}
            className="px-3 py-1.5 text-xs bg-emerald-600 text-white rounded-md hover:bg-emerald-700 disabled:opacity-50"
          >
            {submitting ? 'Submitting…' : `Submit ${status}`}
          </button>
        </div>
      )}
    </div>
  )
}
