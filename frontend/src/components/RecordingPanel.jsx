import { useEffect, useRef, useState } from 'react'
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
  insertRecordingWait,
  insertRecordingScreenshotAfter,
  updateRecordedStep,
  deleteRecordedStep,
  reorderRecordedSteps,
  requestLocatorTest,
  saveRecordingAsDraft,
  previewWorkflowRun,
  getWorkflowRun,
} from '../api/client'
import StatusBadge from './StatusBadge.jsx'
import RunResultBanner from './RunResultBanner.jsx'
import { describeStep, STEP_RUN_ICON } from '../utils/describeStep.js'

const RUN_TERMINAL_STATUSES = new Set([
  'PASSED', 'FAILED', 'BLOCKED', 'NOT_APPLICABLE', 'CANCELLED', 'RUNNER_LOST', 'SYSTEM_ERROR',
])

// A sensitive field's real value is never captured (see content.js) --
// the tester must supply a ${VAR_NAME} placeholder before a recording
// with one can be saved. Guessing a sensible default from the field's
// own description removes the "learn the ${VAR} syntax from a blank
// box" friction; the tester can still edit or clear it afterward.
const SECRET_NAME_HINTS = [
  [/otp|one.?time.?pass/i, 'OTP'],
  [/token/i, 'TOKEN'],
  [/passcode|pin\b/i, 'PASSCODE'],
  [/cvv|cvc/i, 'CARD_CVV'],
  [/card.?number/i, 'CARD_NUMBER'],
  [/password|pwd/i, 'PASSWORD'],
  [/secret/i, 'SECRET'],
]

function suggestSecretName(step, fallbackIndex) {
  const haystack = `${step.target_summary || ''} ${step.locator_value || ''}`
  for (const [pattern, name] of SECRET_NAME_HINTS) {
    if (pattern.test(haystack)) return `\${LOGIN_${name}}`
  }
  return `\${SECRET_${fallbackIndex}}`
}

/** Recorder control panel. The tester chooses an existing browser tab
 * through the QA-Again extension, then records normal interactions in
 * that tab. This panel shows the captured steps and review controls. */
export default function RecordingPanel({ slug, workflowId, canEdit, nextRevisionLabel = 'v1', onDraftSaved }) {
  const [session, setSession] = useState(null)
  const [checkpointText, setCheckpointText] = useState('')
  const [waitSeconds, setWaitSeconds] = useState('2')
  const [error, setError] = useState(null)
  const [saving, setSaving] = useState(false)
  const [extensionToken, setExtensionToken] = useState(null)
  const [pairingCopied, setPairingCopied] = useState(false)
  const [savedRevision, setSavedRevision] = useState(null)
  const [showActionTools, setShowActionTools] = useState(false)
  const [previewRun, setPreviewRun] = useState(null)
  const [previewError, setPreviewError] = useState(null)
  // Tracks which sensitive steps we've already auto-suggested a name
  // for, so a tester deliberately clearing the field never gets
  // silently overwritten again on the next poll/refresh.
  const suggestedStepIds = useRef(new Set())

  useEffect(() => {
    if (!session?.id) return
    const poll = () => getRecordingSession(slug, session.id).then(setSession).catch(() => {})
    const interval = setInterval(poll, 1500)
    return () => clearInterval(interval)
  }, [slug, session?.id])

  useEffect(() => {
    if (!previewRun?.id || RUN_TERMINAL_STATUSES.has(previewRun.status)) return
    const poll = () => getWorkflowRun(slug, previewRun.id).then(setPreviewRun).catch(() => {})
    const interval = setInterval(poll, 1500)
    return () => clearInterval(interval)
  }, [slug, previewRun?.id, previewRun?.status])

  useEffect(() => {
    if (session?.status !== 'STOPPED') return
    const sensitiveSteps = (session.recorded_steps || []).filter((s) => s.is_sensitive)
    const toSuggest = sensitiveSteps.filter((s) => !s.input_value && !suggestedStepIds.current.has(s.id))
    if (toSuggest.length === 0) return
    let fallbackIndex = 1
    Promise.all(
      toSuggest.map((s) => {
        suggestedStepIds.current.add(s.id)
        const name = suggestSecretName(s, fallbackIndex++)
        return updateRecordedStep(slug, session.id, s.id, { input_value: name })
      }),
    ).then(refresh)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slug, session?.id, session?.status, session?.recorded_steps])

  const handleStart = async () => {
    setError(null)
    try {
      // The extension replaces this with the selected tab's real URL.
      const s = await createRecordingSession(slug, workflowId, 'about:blank')
      setSession(s)
      setSavedRevision(null)
      setPairingCopied(false)
      try {
        const result = await authorizeExtension(slug, s.id)
        setExtensionToken(result.pairing_code)
      } catch (err) {
        setExtensionToken(null)
        setError(err.response?.data?.detail || 'Could not create the browser connection code. Try again below.')
      }
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not start recording. Please try again.')
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
      setExtensionToken(result.pairing_code)
      setPairingCopied(false)
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not authorize the extension')
    }
  }

  const handleCopyPairingCode = async () => {
    try {
      await navigator.clipboard.writeText(extensionToken)
      setPairingCopied(true)
    } catch {
      setError('Could not copy automatically. Select the connection code and copy it manually.')
    }
  }
  const handleDiscard = async () => {
    if (!window.confirm('Discard this recording? All captured steps will be deleted.')) return
    await discardRecordingSession(slug, session.id)
    setSession(null)
    setExtensionToken(null)
  }

  const handleInsertCheckpoint = async (e) => {
    e.preventDefault()
    if (!checkpointText.trim()) return
    await insertRecordingCheckpoint(slug, session.id, checkpointText.trim())
    setCheckpointText('')
    refresh()
  }

  const handleInsertWait = async (e) => {
    e.preventDefault()
    const seconds = Number(waitSeconds)
    if (!seconds || seconds <= 0) return
    await insertRecordingWait(slug, session.id, Math.round(seconds * 1000))
    refresh()
  }

  const handleInsertScreenshotAfter = async (step) => {
    await insertRecordingScreenshotAfter(slug, session.id, step.id)
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

  const handleTestItNow = async () => {
    setPreviewError(null)
    try {
      const run = await previewWorkflowRun(slug, savedRevision.id)
      setPreviewRun(run)
    } catch (err) {
      setPreviewError(err.response?.data?.detail || 'Could not start a preview run')
    }
  }

  const handleSaveAsDraft = async (e) => {
    e.preventDefault()
    setSaving(true)
    setError(null)
    try {
      const revision = await saveRecordingAsDraft(slug, session.id, nextRevisionLabel)
      setSession(null)
      setSavedRevision(null)
      onDraftSaved?.(revision)
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not save this test. Please review the highlighted actions.')
    } finally {
      setSaving(false)
    }
  }

  if (!canEdit) return null

  if (!session) {
    return (
      <div className="space-y-3">
        <div className="flex items-center gap-3 flex-wrap">
            <button onClick={handleStart} className="px-4 py-2 bg-emerald-600 text-white text-sm font-medium rounded-md hover:bg-emerald-700">
              ● Record
            </button>
          {error && <p className="text-xs text-red-600">{error}</p>}
        </div>

        {savedRevision && (
          <div className="bg-white border border-purple-200 rounded-lg p-4 space-y-2">
            <p className="text-xs font-medium text-gray-500 uppercase">
              Draft revision "{savedRevision.revision_label}" saved
            </p>
            {!previewRun ? (
              <>
                <p className="text-xs text-gray-500">
                  See it run right now, without publishing -- a preview run is never counted in reports and doesn't
                  require an admin.
                </p>
                <button onClick={handleTestItNow} className="px-3 py-1.5 text-xs bg-purple-600 text-white rounded-md hover:bg-purple-700">
                  Test It Now
                </button>
                {previewError && <p className="text-xs text-red-600">{previewError}</p>}
              </>
            ) : (
              <>
                <p className="text-[10px] font-medium text-purple-700 uppercase">
                  Preview (not published, not counted in reports)
                </p>
                <RunResultBanner status={previewRun.status} />
                {(previewRun.step_runs || []).length > 0 && (
                  <ol className="space-y-1 mt-1">
                    {previewRun.step_runs.map((sr) => (
                      <li key={sr.id} className="text-xs flex items-center gap-2">
                        <span>{STEP_RUN_ICON[sr.status] || '⚪'}</span>
                        <span>{describeStep(sr).text}</span>
                      </li>
                    ))}
                  </ol>
                )}
                <button onClick={handleTestItNow} className="px-3 py-1.5 text-xs border border-purple-300 text-purple-700 rounded-md hover:bg-purple-50">
                  Run Preview Again
                </button>
              </>
            )}
          </div>
        )}
      </div>
    )
  }

  const steps = session.recorded_steps || []
  const isRecording = session.status === 'RECORDING'
  const isPaused = session.status === 'PAUSED'
  const isStopped = session.status === 'STOPPED'
  const canTestLocator = (isRecording || isPaused) && showActionTools

  return (
    <div className="bg-white border border-emerald-300 rounded-lg p-4 space-y-3">
      <div className="flex items-center gap-2 flex-wrap">
        <p className="font-semibold text-gray-900">{session.status === 'REQUESTED' ? 'Connecting recorder…' : 'Recording'}</p>
        {session.status !== 'REQUESTED' && <StatusBadge status={session.status} />}
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
        <div className="bg-emerald-50 border border-emerald-200 rounded-md p-4 text-sm">
          <p className="font-semibold text-gray-900">Choose the tab you want to record</p>
          <ol className="mt-2 ml-5 list-decimal text-xs text-gray-600 space-y-1">
            <li>Copy the connection code below.</li>
            <li>Switch to the tab where this journey should begin.</li>
            <li>Open the QA-Again Recorder extension, paste the code, then click <strong>Use This Tab</strong>.</li>
            <li>Use the website normally. Return here and click <strong>Stop Recording</strong> when finished.</li>
          </ol>
          {extensionToken ? (
            <div className="mt-3 flex flex-col sm:flex-row gap-2">
              <input
                readOnly
                value={extensionToken}
                aria-label="Recording connection code"
                onFocus={(event) => event.target.select()}
                className="min-w-0 flex-1 bg-white border border-emerald-200 rounded px-2 py-1.5 text-xs font-mono"
              />
              <button
                onClick={handleCopyPairingCode}
                className="px-3 py-1.5 bg-emerald-600 text-white rounded hover:bg-emerald-700 whitespace-nowrap"
              >
                {pairingCopied ? 'Copied!' : 'Copy Code'}
              </button>
            </div>
          ) : (
            <button onClick={handleAuthorizeExtension} className="mt-3 px-3 py-1.5 border border-emerald-400 text-emerald-700 rounded hover:bg-emerald-100">
              Create connection code
            </button>
          )}
        </div>
      )}

      {(isRecording || isPaused) && (
        <div className={showActionTools ? 'flex gap-2 flex-wrap' : 'hidden'}>
          <form onSubmit={handleInsertCheckpoint} className="flex gap-2 flex-1 min-w-[240px]">
            <input
              value={checkpointText}
              onChange={(e) => setCheckpointText(e.target.value)}
              placeholder="Insert a manual checkpoint instruction…"
              className="flex-1 px-2 py-1 text-xs border border-gray-300 rounded"
            />
            <button type="submit" className="px-2 py-1 text-xs border border-gray-300 rounded hover:bg-gray-50 whitespace-nowrap">
              + Insert Checkpoint
            </button>
          </form>
          <form onSubmit={handleInsertWait} className="flex gap-2 items-center">
            <input
              type="number"
              min="0.1"
              step="0.1"
              value={waitSeconds}
              onChange={(e) => setWaitSeconds(e.target.value)}
              title="Seconds to pause here during replay"
              className="w-16 px-2 py-1 text-xs border border-gray-300 rounded"
            />
            <span className="text-xs text-gray-400">sec</span>
            <button type="submit" className="px-2 py-1 text-xs border border-gray-300 rounded hover:bg-gray-50 whitespace-nowrap">
              + Insert Wait
            </button>
          </form>
        </div>
      )}

      <div>
        <div className="flex items-center justify-between gap-2 mb-2">
          <p className="text-xs font-medium text-gray-500">Actions ({steps.length})</p>
          {steps.length > 0 && (
            <button onClick={() => setShowActionTools((open) => !open)} className="text-xs text-gray-400 hover:text-gray-600">
              {showActionTools ? 'Hide action tools' : 'Action tools'}
            </button>
          )}
        </div>
        {steps.length === 0 ? (
          <p className="text-xs text-gray-400">Nothing captured yet — interact with the target tab after connecting the extension.</p>
        ) : (
          <ol className="space-y-1">
            {steps.map((s, i) => (
              <li key={s.id} className={`text-xs border rounded px-2 py-1.5 ${s.needs_review ? 'border-amber-300 bg-amber-50' : 'border-gray-100'}`}>
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-mono text-gray-400 w-5">{i + 1}</span>
                  <span>
                    {describeStep(s).icon} {describeStep(s).text}
                  </span>
                  {s.is_sensitive && <span className="px-1 rounded bg-purple-100 text-purple-700">sensitive</span>}
                  {s.needs_review && <span className="text-amber-700 font-medium">needs review</span>}
                  <span className="ml-auto flex gap-1">
                    {canTestLocator && s.locator_value && (
                      <button onClick={() => handleTestLocator(s)} className="px-1 border rounded">
                        Test locator
                      </button>
                    )}
                    {showActionTools && (isPaused || isStopped) && s.step_type !== 'SCREENSHOT' && (
                      <button
                        onClick={() => handleInsertScreenshotAfter(s)}
                        className="px-1.5 border border-emerald-300 text-emerald-700 rounded whitespace-nowrap hover:bg-emerald-50"
                        title="Add a screenshot immediately after this action"
                      >
                        📷 Add screenshot after this action
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
                {(s.locator_value || s.input_value) && (
                  <p className={showActionTools ? 'text-gray-400 mt-0.5' : 'hidden'}>
                    {s.locator_value && (
                      <>
                        {s.step_type} {s.locator_strategy}={s.locator_value}
                      </>
                    )}
                    {s.input_value && !s.is_sensitive && <> — value: {s.input_value}</>}
                  </p>
                )}
                {s.locator_warnings_json && (
                  <p className="text-amber-700 mt-1">This action may need a quick review.</p>
                )}
                {s.locator_test_result_json && (
                  <p className={showActionTools ? 'text-gray-500 mt-1' : 'hidden'}>
                    Locator test: {JSON.parse(s.locator_test_result_json).ok ? '✅ matched exactly 1 element' : `❌ ${JSON.parse(s.locator_test_result_json).message}`}
                  </p>
                )}
                {isStopped && s.is_sensitive && (
                  <div className="mt-1 flex items-center gap-1">
                    <span className="text-gray-500">Variable name:</span>
                    <input
                      // Remounts (re-applying defaultValue) whenever the
                      // SAVED value changes -- e.g. right after the
                      // auto-suggestion above lands -- without losing
                      // in-progress keystrokes on every render otherwise
                      // (this is an uncontrolled input on purpose, so a
                      // slow network blip mid-typing can't clobber it).
                      key={s.input_value || ''}
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
        <form onSubmit={handleSaveAsDraft} className="flex justify-end border-t border-gray-100 pt-3">
          <input
            value={nextRevisionLabel}
            readOnly
            placeholder="Draft revision label (e.g. recorded-v1)"
            className="hidden"
          />
          <button type="submit" disabled={saving || steps.length === 0} className="px-5 py-2 bg-emerald-600 text-white text-sm font-medium rounded-md hover:bg-emerald-700 disabled:opacity-50">
            {saving ? 'Saving…' : 'Save Test'}
          </button>
        </form>
      )}

      {error && <p className="text-xs text-red-600">{error}</p>}
    </div>
  )
}
