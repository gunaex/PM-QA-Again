import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { NavLink, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import {
  getCycle,
  listCycleResults,
  getCycleResult,
  updateCycleResult,
  reviewCycleResult,
  getCycleResultHistory,
  lockCycle,
  reopenCycle,
  rerunCycle,
} from '../api/client'
import { useAuth } from '../auth/AuthContext.jsx'
import StatusBadge from '../components/StatusBadge.jsx'
import EvidenceGallery from '../components/EvidenceGallery.jsx'

const STATUS_FILTERS = ['ALL', 'NOT_RUN', 'PASS', 'FAIL', 'BLOCKED', 'NOT_APPLICABLE']

export default function CycleExecution() {
  const { slug, cycleId } = useParams()
  const { user } = useAuth()
  const canEdit = user?.role === 'ADMIN' || user?.role === 'TESTER'
  const isAdmin = user?.role === 'ADMIN'
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()

  const [cycle, setCycle] = useState(null)
  const [rerunning, setRerunning] = useState(false)
  // Lightweight list (no case action/expected/setup/validation markdown —
  // see docs/PERFORMANCE_FAST_PASS.md) used for the sidebar/filters.
  const [results, setResults] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [selectedId, setSelectedId] = useState(null)
  const [filter, setFilter] = useState('ALL')
  // Per-result unsaved draft — keyed by result id so switching cases
  // never loses in-progress typing (rebuild prompt §12 execution screen
  // requirement).
  const [drafts, setDrafts] = useState({})
  const [saveState, setSaveState] = useState({}) // resultId -> 'idle'|'saving'|'saved'|'error'
  const [history, setHistory] = useState(null)
  const [showHistory, setShowHistory] = useState(false)
  const [showCompletion, setShowCompletion] = useState(false)

  // Full result detail (adds case_action_md/expected/setup/validation),
  // fetched lazily per selection and cached for the rest of this page
  // session — switching back to an already-opened case is instant.
  const [detailCache, setDetailCache] = useState({})
  const [detailLoadingId, setDetailLoadingId] = useState(null)
  const detailRequestSeq = useRef(0)
  // Captures a status-button click synchronously. This prevents a rapid
  // PASS -> Save & Next sequence from re-submitting the stale NOT_RUN
  // status before React has rendered the saved response.
  const intendedStatusRef = useRef({})

  const load = () => {
    setLoading(true)
    setError(null)
    Promise.all([getCycle(slug, cycleId), listCycleResults(slug, cycleId)])
      .then(([c, r]) => {
        setCycle(c)
        setResults(r)
        // Deep-link support (Continue Last Test / Quick Manual Test /
        // Save & Next): a ?resultId= in the URL selects that exact case
        // instead of always defaulting to the first one.
        const requestedId = Number(searchParams.get('resultId'))
        const requested = requestedId && r.some((x) => x.id === requestedId) ? requestedId : null
        setSelectedId((prev) => prev ?? requested ?? r[0]?.id ?? null)
      })
      .catch(() => setError('Could not reach the backend.'))
      .finally(() => setLoading(false))
  }

  useEffect(load, [slug, cycleId])

  // Lazily fetch full case detail for whichever result is selected. A
  // request sequence number lets a rapid second selection make an
  // in-flight response for the previous one a no-op, so fast clicking
  // through the case list never shows stale detail.
  useEffect(() => {
    if (!selectedId || detailCache[selectedId]) return
    const seq = ++detailRequestSeq.current
    setDetailLoadingId(selectedId)
    getCycleResult(slug, cycleId, selectedId)
      .then((full) => {
        if (seq !== detailRequestSeq.current) return
        setDetailCache((prev) => ({ ...prev, [selectedId]: full }))
      })
      .catch(() => {
        if (seq !== detailRequestSeq.current) return
        setError('Could not load case details')
      })
      .finally(() => {
        if (seq === detailRequestSeq.current) setDetailLoadingId(null)
      })
  }, [slug, cycleId, selectedId, detailCache])

  const selectedLite = useMemo(() => results.find((r) => r.id === selectedId) || null, [results, selectedId])
  const selected = useMemo(
    () => (selectedLite ? { ...selectedLite, ...(detailCache[selectedId] || {}) } : null),
    [selectedLite, detailCache, selectedId]
  )
  const detailLoading = detailLoadingId === selectedId && !detailCache[selectedId]
  const draft = selectedId ? drafts[selectedId] || {} : {}
  const isLocked = cycle?.status === 'LOCKED'

  const filteredResults = filter === 'ALL' ? results : results.filter((r) => r.status === filter)

  const updateDraft = (patch) => {
    if (!selectedId) return
    setDrafts((prev) => ({ ...prev, [selectedId]: { ...prev[selectedId], ...patch } }))
  }

  const selectCase = (id) => {
    setSelectedId(id)
    setShowHistory(false)
    setHistory(null)
    setError(null)
    setShowCompletion(false)
    setSearchParams({})
  }

  const submitStatus = async (status) => {
    if (!selected) return false
    intendedStatusRef.current[selected.id] = status
    const payload = {
      status,
      actual_result_md: draft.actual_result_md ?? selected.actual_result_md ?? '',
      blocked_reason: draft.blocked_reason ?? selected.blocked_reason ?? '',
      na_reason: draft.na_reason ?? selected.na_reason ?? '',
      defect_reference: draft.defect_reference ?? selected.defect_reference ?? '',
    }
    setSaveState((prev) => ({ ...prev, [selected.id]: 'saving' }))
    setError(null)
    try {
      const updated = await updateCycleResult(slug, cycleId, selected.id, payload)
      setResults((prev) => prev.map((r) => (r.id === updated.id ? updated : r)))
      setDetailCache((prev) => ({ ...prev, [updated.id]: updated }))
      setDrafts((prev) => ({ ...prev, [selected.id]: undefined }))
      setSaveState((prev) => ({ ...prev, [selected.id]: 'saved' }))
      const refreshedCycle = await getCycle(slug, cycleId)
      setCycle(refreshedCycle)
      return true
    } catch (err) {
      setSaveState((prev) => ({ ...prev, [selected.id]: 'error' }))
      setError(err.response?.data?.detail || 'Could not save result')
      return false
    }
  }

  const goToNextCase = useCallback(() => {
    setResults((currentResults) => {
      const idx = currentResults.findIndex((r) => r.id === selectedId)
      const next = currentResults[idx + 1]
      if (next) {
        setSelectedId(next.id)
        setShowHistory(false)
        setHistory(null)
        setError(null)
        setShowCompletion(false)
      } else {
        setShowCompletion(true)
      }
      return currentResults
    })
  }, [selectedId])

  // "Save & Next": persists whatever's in the draft (actual result /
  // blocked / N-A reason) against the CURRENT status without requiring
  // a fresh PASS/FAIL/BLOCKED/N-A click first, then advances to the
  // next case — the common "I already marked this, just move on" path.
  const handleSaveAndNext = async () => {
    const intendedStatus = intendedStatusRef.current[selected.id] || selected.status
    const ok = await submitStatus(intendedStatus)
    if (ok) goToNextCase()
  }

  const handleReview = async (reviewStatus) => {
    if (!selected) return
    const updated = await reviewCycleResult(slug, cycleId, selected.id, { review_status: reviewStatus })
    setResults((prev) => prev.map((r) => (r.id === updated.id ? updated : r)))
    setDetailCache((prev) => ({ ...prev, [updated.id]: updated }))
  }

  const toggleHistory = async () => {
    if (!selected) return
    if (!showHistory) {
      const h = await getCycleResultHistory(slug, cycleId, selected.id)
      setHistory(h)
    }
    setShowHistory((v) => !v)
  }

  const handleLock = async () => {
    if (!window.confirm('Lock this cycle? All results become read-only until an admin reopens it.')) return
    const updated = await lockCycle(slug, cycleId)
    setCycle(updated)
  }

  const handleReopen = async () => {
    const reason = window.prompt('Reason for reopening this locked cycle:')
    if (!reason) return
    const updated = await reopenCycle(slug, cycleId, reason)
    setCycle(updated)
  }

  const handleRerun = async (mode) => {
    const label = mode === 'all' ? 'the entire cycle' : 'FAIL/BLOCKED cases only'
    if (!window.confirm(`Rerun ${label}? This creates a brand-new cycle — this cycle is never changed.`)) return
    try {
      const newCycle = await rerunCycle(slug, cycleId, mode)
      navigate(`/${slug}/cycles/${newCycle.id}`)
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not rerun this cycle')
    }
  }

  // Keyboard shortcuts (Alt+key, so ordinary typing in the Actual
  // Result / Blocked / N-A fields is never accidentally intercepted):
  // Alt+P/F/B/A for PASS/FAIL/BLOCKED/N-A, Alt+Enter for Save & Next.
  useEffect(() => {
    const onKeyDown = (e) => {
      if (!e.altKey || !canEdit || isLocked || !selected) return
      const key = e.key.toLowerCase()
      if (key === 'p') { e.preventDefault(); submitStatus('PASS') }
      else if (key === 'f') { e.preventDefault(); submitStatus('FAIL') }
      else if (key === 'b') { e.preventDefault(); submitStatus('BLOCKED') }
      else if (key === 'a') { e.preventDefault(); submitStatus('NOT_APPLICABLE') }
      else if (key === 'enter') { e.preventDefault(); handleSaveAndNext() }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  })

  if (loading) return <p className="text-gray-500 text-sm">Loading…</p>
  if (error && !cycle)
    return (
      <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded-md px-4 py-3">
        <p>{error}</p>
        <button onClick={load} className="mt-2 text-red-800 font-medium hover:underline">
          Retry
        </button>
      </div>
    )

  const saveLabel = { saving: 'Saving…', saved: 'Saved', error: 'Error saving' }[saveState[selectedId]]

  return (
    <div className="space-y-4">
      <div>
        <NavLink to={`/${slug}/cycles`} className="text-sm text-gray-500 hover:text-gray-800">
          &larr; Test Cycles
        </NavLink>
        <div className="flex items-center gap-2 flex-wrap mt-1">
          <h2 className="text-xl font-semibold text-gray-900">{cycle.name}</h2>
          <StatusBadge status={cycle.status} />
          <span className="text-xs text-gray-500">{cycle.environment}</span>
          <div className="ml-auto flex gap-2">
            {canEdit && (
              <>
                <button onClick={() => handleRerun('all')} className="text-xs border border-gray-300 rounded-md px-2 py-1 hover:bg-gray-50">
                  Rerun entire cycle
                </button>
                <button onClick={() => handleRerun('fail_blocked')} className="text-xs border border-gray-300 rounded-md px-2 py-1 hover:bg-gray-50">
                  Rerun FAIL/BLOCKED only
                </button>
              </>
            )}
            {isAdmin && cycle.status !== 'LOCKED' && (
              <button onClick={handleLock} className="text-xs border border-gray-300 rounded-md px-2 py-1 hover:bg-gray-50">
                Lock Cycle
              </button>
            )}
            {isAdmin && cycle.status === 'LOCKED' && (
              <button onClick={handleReopen} className="text-xs border border-gray-300 rounded-md px-2 py-1 hover:bg-gray-50">
                Reopen (admin)
              </button>
            )}
          </div>
        </div>
        {isLocked && (
          <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-md px-3 py-2 mt-2">
            This cycle is locked — results are read-only. An admin must reopen it to make changes.
          </p>
        )}
        {error && (
          <p className="text-xs text-red-700 bg-red-50 border border-red-200 rounded-md px-3 py-2 mt-2">{error}</p>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[280px_1fr] gap-4">
        {/* Left panel: case list + filters */}
        <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
          <div className="flex flex-wrap gap-1 p-2 border-b border-gray-100">
            {STATUS_FILTERS.map((f) => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={`px-2 py-1 text-xs rounded ${filter === f ? 'bg-emerald-600 text-white' : 'text-gray-600 hover:bg-gray-100'}`}
              >
                {f}
              </button>
            ))}
          </div>
          <div className="max-h-[60vh] overflow-y-auto divide-y divide-gray-50">
            {filteredResults.map((r) => (
              <button
                key={r.id}
                onClick={() => selectCase(r.id)}
                className={`w-full text-left px-3 py-2 hover:bg-gray-50 ${selectedId === r.id ? 'bg-emerald-50' : ''}`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-[11px] text-gray-500">{r.checkpoint_code}</span>
                  <StatusBadge status={r.status} />
                </div>
                <p className="text-xs text-gray-800 mt-0.5 truncate">{r.case_title}</p>
              </button>
            ))}
          </div>
        </div>

        {/* Keep the saved case visible below this summary. Hiding the
            detail panel made a successful final save look like data loss. */}
        {showCompletion && (
          <div className="bg-white border border-emerald-200 rounded-lg p-6 text-center space-y-3">
            <p className="text-lg font-semibold text-gray-900">All cases reached 🎉</p>
            <div className="flex justify-center gap-4 text-sm">
              {['PASS', 'FAIL', 'BLOCKED', 'NOT_APPLICABLE', 'NOT_RUN'].map((s) => (
                <span key={s} className="text-gray-600">
                  <StatusBadge status={s} /> <span className="font-semibold text-gray-900">{results.filter((r) => r.status === s).length}</span>
                </span>
              ))}
            </div>
            <button onClick={() => setShowCompletion(false)} className="text-sm text-emerald-600 hover:underline">
              Dismiss summary
            </button>
          </div>
        )}

        {/* Main panel */}
        {selected && (
          <div className="bg-white border border-gray-200 rounded-lg p-5 space-y-4">
            <div>
              <div className="flex items-center gap-2 flex-wrap">
                <span className="font-mono text-xs text-gray-500">{selected.checkpoint_code}</span>
                <h3 className="font-medium text-gray-900">{selected.case_title}</h3>
                {selected.case_priority && (
                  <span className="px-1.5 py-0.5 text-[10px] uppercase rounded bg-gray-100 text-gray-500">
                    {selected.case_priority}
                  </span>
                )}
              </div>
            </div>

            {detailLoading ? (
              <p className="text-xs text-gray-400">Loading case details…</p>
            ) : (
              <>
                {selected.case_setup_md && (
                  <div>
                    <p className="text-xs font-medium text-gray-500 uppercase">Setup</p>
                    <p className="text-sm text-gray-800 whitespace-pre-wrap">{selected.case_setup_md}</p>
                  </div>
                )}
                <div>
                  <p className="text-xs font-medium text-gray-500 uppercase">Action</p>
                  <p className="text-sm text-gray-800 whitespace-pre-wrap">{selected.case_action_md}</p>
                </div>
                {selected.case_validation_md && (
                  <div>
                    <p className="text-xs font-medium text-gray-500 uppercase">Validation</p>
                    <p className="text-sm text-gray-800 whitespace-pre-wrap">{selected.case_validation_md}</p>
                  </div>
                )}
                <div>
                  <p className="text-xs font-medium text-gray-500 uppercase">Expected Result</p>
                  <p className="text-sm text-gray-800 whitespace-pre-wrap">{selected.case_expected_result_md}</p>
                </div>
              </>
            )}

            <EvidenceGallery
              key={selected.id}
              slug={slug}
              cycleId={cycleId}
              resultId={selected.id}
              canEdit={canEdit}
              isAdmin={isAdmin}
              isLocked={isLocked}
            />

            <div>
              <p className="text-xs font-medium text-gray-500 uppercase mb-1">Actual Result</p>
              <textarea
                disabled={isLocked || !canEdit}
                value={draft.actual_result_md ?? selected.actual_result_md ?? ''}
                onChange={(e) => updateDraft({ actual_result_md: e.target.value })}
                rows={3}
                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500 disabled:bg-gray-50"
                placeholder="What actually happened (required for FAIL)"
              />
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <p className="text-xs font-medium text-gray-500 uppercase mb-1">Blocked Reason</p>
                <input
                  disabled={isLocked || !canEdit}
                  value={draft.blocked_reason ?? selected.blocked_reason ?? ''}
                  onChange={(e) => updateDraft({ blocked_reason: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500 disabled:bg-gray-50"
                  placeholder="Required for BLOCKED"
                />
              </div>
              <div>
                <p className="text-xs font-medium text-gray-500 uppercase mb-1">N/A Reason</p>
                <input
                  disabled={isLocked || !canEdit}
                  value={draft.na_reason ?? selected.na_reason ?? ''}
                  onChange={(e) => updateDraft({ na_reason: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500 disabled:bg-gray-50"
                  placeholder="Required for N/A"
                />
              </div>
            </div>

            {selected.status === 'NOT_APPLICABLE' && (
              <div className="flex items-center gap-2 text-xs">
                <span className="text-gray-500">Review:</span>
                <StatusBadge status={selected.review_status} />
                {isAdmin && selected.review_status === 'UNREVIEWED' && (
                  <>
                    <button onClick={() => handleReview('ACCEPTED')} className="text-emerald-600 hover:underline">
                      Accept
                    </button>
                    <button onClick={() => handleReview('CHANGES_REQUESTED')} className="text-red-500 hover:underline">
                      Request changes
                    </button>
                  </>
                )}
              </div>
            )}

            {/* Sticky action area */}
            {canEdit && !isLocked && (
              <div className="sticky bottom-0 bg-white border-t border-gray-100 pt-3 flex items-center gap-2 flex-wrap">
                <button
                  onClick={() => submitStatus('PASS')}
                  className="px-3 py-1.5 text-sm bg-green-600 text-white rounded-md hover:bg-green-700"
                  title="Alt+P"
                >
                  PASS
                </button>
                <button
                  onClick={() => submitStatus('FAIL')}
                  className="px-3 py-1.5 text-sm bg-red-600 text-white rounded-md hover:bg-red-700"
                  title="Alt+F"
                >
                  NG
                </button>
                <button
                  onClick={() => submitStatus('BLOCKED')}
                  className="px-3 py-1.5 text-sm bg-amber-500 text-white rounded-md hover:bg-amber-600"
                  title="Alt+B"
                >
                  BLOCKED
                </button>
                <button
                  onClick={() => submitStatus('NOT_APPLICABLE')}
                  className="px-3 py-1.5 text-sm border border-gray-300 rounded-md hover:bg-gray-50"
                  title="Alt+A"
                >
                  N/A
                </button>
                <button
                  onClick={handleSaveAndNext}
                  className="px-3 py-1.5 text-sm bg-gray-800 text-white rounded-md hover:bg-gray-900"
                  title="Alt+Enter"
                >
                  Save &amp; Next
                </button>
                {saveLabel && (
                  <span className={`text-xs ${saveState[selectedId] === 'error' ? 'text-red-600' : 'text-gray-500'}`}>
                    {saveLabel}
                  </span>
                )}
                <button onClick={toggleHistory} className="ml-auto text-xs text-gray-500 hover:underline">
                  {showHistory ? 'Hide history' : 'Show history'}
                </button>
              </div>
            )}
            {(!canEdit || isLocked) && (
              <button onClick={toggleHistory} className="text-xs text-gray-500 hover:underline">
                {showHistory ? 'Hide history' : 'Show history'}
              </button>
            )}

            {showHistory && (
              <div className="border-t border-gray-100 pt-3">
                <p className="text-xs font-medium text-gray-500 uppercase mb-2">Result History</p>
                {!history || history.length === 0 ? (
                  <p className="text-xs text-gray-400">No changes recorded yet.</p>
                ) : (
                  <ul className="space-y-2">
                    {history.map((h) => (
                      <li key={h.id} className="text-xs text-gray-600 border-l-2 border-gray-200 pl-2">
                        <span className="font-medium">rev {h.result_revision_no}</span> — <StatusBadge status={h.status} />{' '}
                        by {h.changed_by} at {new Date(h.changed_at).toLocaleString()}
                        {h.actual_result_md && <div className="text-gray-500 mt-0.5">{h.actual_result_md}</div>}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
