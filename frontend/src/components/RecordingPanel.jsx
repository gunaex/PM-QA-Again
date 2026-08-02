import { useEffect, useState } from 'react'
import {
  createRecordingSession,
  getRecordingSession,
  pauseRecordingSession,
  resumeRecordingSession,
  stopRecordingSession,
  discardRecordingSession,
  undoLastRecordedStep,
  authorizeExtension,
  insertRecordingCheckpoint,
  updateRecordedStep,
  deleteRecordedStep,
  reorderRecordedSteps,
  requestLocatorTest,
  saveRecordingAsDraft,
} from '../api/client'
import StatusBadge from './StatusBadge.jsx'

const ACTIVE_STATUSES = new Set(['REQUESTED', 'CLAIMED', 'RECORDING', 'PAUSED'])

/** HYB-3 recorder control panel. Recording itself happens inside a
 * separate Playwright-controlled browser the QA Runner process
 * launches (never this page's own browser) -- this panel is the
 * remote control: start/pause/resume/stop, live captured-step list,
 * review/edit before saving, save as DRAFT (never auto-published). */
export default function RecordingPanel({ slug, workflowId, canEdit, onDraftSaved }) {
  const [session, setSession] = useState(null)
  const [targetUrl, setTargetUrl] = useState(`${window.location.origin}/login`)
  const [checkpointText, setCheckpointText] = useState('')
  const [revisionLabel, setRevisionLabel] = useState('')
  const [error, setError] = useState(null)
  const [saving, setSaving] = useState(false)
  const [extensionToken, setExtensionToken] = useState(null)

  useEffect(() => {
    if (!session?.id) return
    const poll = () => getRecordingSession(slug, session.id).then(setSession).catch(() => {})
    const interval = setInterval(poll, 1500)
    return () => clearInterval(interval)
  }, [slug, session?.id])

  const handleStart = async () => {
    setError(null)
    try {
      const s = await createRecordingSession(slug, workflowId, targetUrl)
      setSession(s)
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not start a recording session')
    }
  }

  const refresh = () => getRecordingSession(slug, session.id).then(setSession)

  const handlePause = () => pauseRecordingSession(slug, session.id).then(refresh)
  const handleResume = () => resumeRecordingSession(slug, session.id).then(refresh)
  const handleStop = () => stopRecordingSession(slug, session.id).then(refresh)
  const handleUndo = async () => {
    try {
      await undoLastRecordedStep(slug, session.id)
      refresh()
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not undo the last step')
    }
  }
  const handleAuthorizeExtension = async () => {
    setError(null)
    try {
      const result = await authorizeExtension(slug, session.id)
      setExtensionToken(result.token)
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not authorize the extension')
    }
  }
  const handleDiscard = async () => {
    if (!window.confirm('Discard this recording? All captured steps will be deleted.')) return
    await discardRecordingSession(slug, session.id)
    setSession(null)
  }

  const handleInsertCheckpoint = async (e) => {
    e.preventDefault()
    if (!checkpointText.trim()) return
    await insertRecordingCheckpoint(slug, session.id, checkpointText.trim())
    setCheckpointText('')
    refresh()
  }

  const handleEditStep = async (step, patch) => {
    await updateRecordedStep(slug, session.id, step.id, patch)
    refresh()
  }

  const handleDeleteStep = async (step) => {
    await deleteRecordedStep(slug, session.id, step.id)
    refresh()
  }

  const moveStep = async (steps, index, direction) => {
    const newIndex = index + direction
    if (newIndex < 0 || newIndex >= steps.length) return
    const reordered = [...steps]
    ;[reordered[index], reordered[newIndex]] = [reordered[newIndex], reordered[index]]
    await reorderRecordedSteps(slug, session.id, reordered.map((s) => s.id))
    refresh()
  }

  const handleTestLocator = async (step) => {
    await requestLocatorTest(slug, session.id, step.id)
    refresh()
  }

  const handleSaveAsDraft = async (e) => {
    e.preventDefault()
    if (!revisionLabel.trim()) return
    setSaving(true)
    setError(null)
    try {
      const revision = await saveRecordingAsDraft(slug, session.id, revisionLabel.trim())
      setSession(null)
      setRevisionLabel('')
      onDraftSaved?.(revision)
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not save this recording as a draft')
    } finally {
      setSaving(false)
    }
  }

  if (!canEdit) return null

  if (!session) {
    return (
      <div className="bg-white border border-gray-200 rounded-lg p-4">
        <p className="text-xs font-medium text-gray-500 uppercase mb-2">Record a Workflow</p>
        <p className="text-xs text-gray-500 mb-2">
          Opens a real, separate browser window that the QA Runner controls — interact with it directly; use the
          buttons below to pause/resume/stop remotely. A runner process must be running (<code>npm run record</code>).
        </p>
        <div className="flex gap-2">
          <input
            value={targetUrl}
            onChange={(e) => setTargetUrl(e.target.value)}
            placeholder="Starting URL"
            className="flex-1 px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
          />
          <button onClick={handleStart} className="px-4 py-2 bg-emerald-600 text-white text-sm font-medium rounded-md hover:bg-emerald-700">
            Start Recording
          </button>
        </div>
        {error && <p className="text-xs text-red-600 mt-2">{error}</p>}
      </div>
    )
  }

  const steps = session.recorded_steps || []
  const isRecording = session.status === 'RECORDING'
  const isPaused = session.status === 'PAUSED'
  const isStopped = session.status === 'STOPPED'
  const canTestLocator = isRecording || isPaused

  return (
    <div className="bg-white border border-emerald-300 rounded-lg p-4 space-y-3">
      <div className="flex items-center gap-2 flex-wrap">
        <p className="text-xs font-medium text-gray-500 uppercase">Recording Session #{session.id}</p>
        <StatusBadge status={session.status} />
        {session.status === 'REQUESTED' && (
          <span className="text-xs text-gray-400">waiting for a runner process (advanced mode) or the Chrome extension to connect…</span>
        )}
        <div className="ml-auto flex gap-2">
          {isRecording && (
            <button onClick={handleUndo} className="px-2 py-1 text-xs border border-gray-300 rounded hover:bg-gray-50">
              Undo last action
            </button>
          )}
          {isRecording && (
            <button onClick={handlePause} className="px-2 py-1 text-xs border border-gray-300 rounded hover:bg-gray-50">
              Pause Recording
            </button>
          )}
          {isPaused && (
            <button onClick={handleUndo} className="px-2 py-1 text-xs border border-gray-300 rounded hover:bg-gray-50">
              Undo last action
            </button>
          )}
          {isPaused && (
            <button onClick={handleResume} className="px-2 py-1 text-xs border border-gray-300 rounded hover:bg-gray-50">
              Resume Recording
            </button>
          )}
          {(isRecording || isPaused) && (
            <button onClick={handleStop} className="px-2 py-1 text-xs bg-gray-800 text-white rounded hover:bg-gray-900">
              Stop Recording
            </button>
          )}
          {session.status !== 'SAVED' && (
            <button onClick={handleDiscard} className="px-2 py-1 text-xs text-red-600 border border-red-200 rounded hover:bg-red-50">
              Discard
            </button>
          )}
        </div>
      </div>

      {session.status === 'REQUESTED' && (
        <div className="border border-dashed border-gray-200 rounded-md p-3 text-xs space-y-2">
          <p className="text-gray-500">
            <strong>Everyday mode:</strong> use the QA-Again Recorder Chrome extension in your own browser tab — no
            terminal needed.
          </p>
          {!extensionToken ? (
            <button onClick={handleAuthorizeExtension} className="px-3 py-1.5 border border-emerald-300 text-emerald-700 rounded hover:bg-emerald-50">
              Authorize Extension
            </button>
          ) : (
            <div className="bg-gray-50 rounded p-2 space-y-1">
              <p className="text-gray-500">
                Paste this into the extension popup along with this backend's URL, project slug (<code>{slug}</code>), and
                session ID (<code>{session.id}</code>). Shown once — copy it now.
              </p>
              <code className="block break-all bg-white border border-gray-200 rounded px-2 py-1 select-all">{extensionToken}</code>
            </div>
          )}
          <p className="text-gray-400">
            Advanced/fallback mode (unchanged): run <code>npm run record</code> in <code>runner/</code> against this same
            session.
          </p>
        </div>
      )}

      {(isRecording || isPaused) && (
        <form onSubmit={handleInsertCheckpoint} className="flex gap-2">
          <input
            value={checkpointText}
            onChange={(e) => setCheckpointText(e.target.value)}
            placeholder="Insert a manual checkpoint instruction…"
            className="flex-1 px-2 py-1 text-xs border border-gray-300 rounded"
          />
          <button type="submit" className="px-2 py-1 text-xs border border-gray-300 rounded hover:bg-gray-50">
            + Insert Checkpoint
          </button>
        </form>
      )}

      <div>
        <p className="text-[10px] font-medium text-gray-400 uppercase mb-1">Captured Steps ({steps.length})</p>
        {steps.length === 0 ? (
          <p className="text-xs text-gray-400">Nothing captured yet — interact with the recording browser window.</p>
        ) : (
          <ol className="space-y-1">
            {steps.map((s, i) => (
              <li key={s.id} className={`text-xs border rounded px-2 py-1.5 ${s.needs_review ? 'border-amber-300 bg-amber-50' : 'border-gray-100'}`}>
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-mono text-gray-400 w-5">{i + 1}</span>
                  <span className="px-1.5 py-0.5 rounded bg-gray-100 font-medium">{s.step_type}</span>
                  {s.locator_value && (
                    <span className="text-gray-500">
                      {s.locator_strategy}={s.locator_value}
                    </span>
                  )}
                  {s.is_sensitive && <span className="px-1 rounded bg-purple-100 text-purple-700">sensitive</span>}
                  {s.input_value && <span className="text-gray-500">value: {s.input_value}</span>}
                  {s.checkpoint_instructions && <span className="text-amber-700">{s.checkpoint_instructions}</span>}
                  {s.needs_review && <span className="text-amber-700 font-medium">needs review</span>}
                  <span className="ml-auto flex gap-1">
                    {canTestLocator && s.locator_value && (
                      <button onClick={() => handleTestLocator(s)} className="px-1 border rounded">
                        Test locator
                      </button>
                    )}
                    {isStopped && (
                      <>
                        <button onClick={() => moveStep(steps, i, -1)} disabled={i === 0} className="px-1 border rounded disabled:opacity-30">
                          ↑
                        </button>
                        <button onClick={() => moveStep(steps, i, 1)} disabled={i === steps.length - 1} className="px-1 border rounded disabled:opacity-30">
                          ↓
                        </button>
                        <button onClick={() => handleDeleteStep(s)} className="px-1 border rounded text-red-600">
                          ✕
                        </button>
                      </>
                    )}
                  </span>
                </div>
                {s.locator_warnings_json && (
                  <p className="text-amber-700 mt-1">⚠ {JSON.parse(s.locator_warnings_json).join('; ')}</p>
                )}
                {s.locator_test_result_json && (
                  <p className="text-gray-500 mt-1">
                    Locator test: {JSON.parse(s.locator_test_result_json).ok ? '✅ matched exactly 1 element' : `❌ ${JSON.parse(s.locator_test_result_json).message}`}
                  </p>
                )}
                {s.locator_test_requested && <p className="text-gray-400 mt-1">Testing locator…</p>}
                {isStopped && s.is_sensitive && (
                  <div className="mt-1 flex items-center gap-1">
                    <span className="text-gray-500">Variable name:</span>
                    <input
                      defaultValue={s.input_value || ''}
                      placeholder="${SECRET_LOGIN_PASSWORD}"
                      onBlur={(e) => e.target.value !== (s.input_value || '') && handleEditStep(s, { input_value: e.target.value })}
                      className="px-1 py-0.5 border border-gray-300 rounded text-xs flex-1"
                    />
                  </div>
                )}
                {isStopped && s.needs_review && (
                  <button onClick={() => handleEditStep(s, { needs_review: false })} className="mt-1 text-amber-800 hover:underline">
                    Mark reviewed
                  </button>
                )}
              </li>
            ))}
          </ol>
        )}
      </div>

      {isStopped && (
        <form onSubmit={handleSaveAsDraft} className="flex gap-2 border-t border-gray-100 pt-3">
          <input
            value={revisionLabel}
            onChange={(e) => setRevisionLabel(e.target.value)}
            placeholder="Draft revision label (e.g. recorded-v1)"
            className="flex-1 px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
          />
          <button type="submit" disabled={saving} className="px-4 py-2 bg-emerald-600 text-white text-sm font-medium rounded-md hover:bg-emerald-700 disabled:opacity-50">
            {saving ? 'Saving…' : 'Save as Draft Revision'}
          </button>
        </form>
      )}

      {error && <p className="text-xs text-red-600">{error}</p>}
    </div>
  )
}
