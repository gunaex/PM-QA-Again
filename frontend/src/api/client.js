import axios from 'axios'

// Local dev: VITE_API_BASE_URL is unset, so this resolves to '/api' — the
// Vite dev server proxy (see vite.config.js) handles it. Production
// (Cloudflare Pages): set VITE_API_BASE_URL to the deployed backend's
// origin (e.g. https://api.qaagain.kanphong.com) so the built frontend
// calls it directly — a cross-origin call, which is why the backend's
// ALLOWED_ORIGINS needs to include the frontend's origin.
const API_BASE = `${import.meta.env.VITE_API_BASE_URL || ''}/api`

// withCredentials: true is required so the httpOnly auth cookies the
// backend sets on login are actually sent back on every request — without
// it every request is anonymous and gets 401.
const api = axios.create({ baseURL: API_BASE, withCredentials: true })

// Registered by AuthProvider so a 401 from any call (session expired,
// cookie cleared) can clear the in-memory user and bounce to /login.
// Login failures (wrong password) and the initial /auth/me probe are
// expected to 401 sometimes and must not trigger this.
let onUnauthorized = null
export const setUnauthorizedHandler = (fn) => {
  onUnauthorized = fn
}

api.interceptors.response.use(
  (response) => response,
  (error) => {
    const url = error.config?.url || ''
    if (error.response?.status === 401 && !url.includes('/auth/login') && !url.includes('/auth/me')) {
      onUnauthorized?.()
    }
    return Promise.reject(error)
  },
)

// Auth
export const login = (email, password) => api.post('/auth/login', { email, password }).then((r) => r.data)
export const logout = () => api.post('/auth/logout').then((r) => r.data)
export const getMe = () => api.get('/auth/me').then((r) => r.data)
export const changePassword = (currentPassword, newPassword) =>
  api
    .post('/auth/change-password', { current_password: currentPassword, new_password: newPassword })
    .then((r) => r.data)

// User management (ADMIN only) + project membership (ADR-0003)
export const listUsers = () => api.get('/auth/users').then((r) => r.data)
export const createUser = (email, password, role) => api.post('/auth/users', { email, password, role }).then((r) => r.data)
export const setUserActive = (userId, active) => api.put(`/auth/users/${userId}`, { active }).then((r) => r.data)
export const listUserProjects = (userId) => api.get(`/auth/users/${userId}/projects`).then((r) => r.data)
export const addUserProject = (userId, projectId) =>
  api.post(`/auth/users/${userId}/projects`, { project_id: projectId }).then((r) => r.data)
export const removeUserProject = (userId, projectId) =>
  api.delete(`/auth/users/${userId}/projects/${projectId}`).then((r) => r.data)

// Projects
export const listProjects = (includeArchived = false) =>
  api.get('/projects', { params: { include_archived: includeArchived } }).then((r) => r.data)
export const createProject = (name, externalProjectUrl = null) =>
  api.post('/projects', { name, external_project_url: externalProjectUrl }).then((r) => r.data)
export const getProject = (slug) => api.get(`/projects/${slug}`).then((r) => r.data)
export const archiveProject = (slug, archived, password) =>
  api.put(`/projects/${slug}/archive`, { archived, password }).then((r) => r.data)
export const deleteProject = (slug, password) =>
  api.delete(`/projects/${slug}`, { data: { password } }).then((r) => r.data)

// Test suites
export const listSuites = (slug, includeSystemGenerated = false) =>
  api.get(`/${slug}/suites`, { params: { include_system_generated: includeSystemGenerated } }).then((r) => r.data)
export const createSuite = (slug, payload) => api.post(`/${slug}/suites`, payload).then((r) => r.data)
export const getSuite = (slug, suiteId) => api.get(`/${slug}/suites/${suiteId}`).then((r) => r.data)
export const updateSuite = (slug, suiteId, payload) =>
  api.put(`/${slug}/suites/${suiteId}`, payload).then((r) => r.data)
export const deleteSuite = (slug, suiteId) => api.delete(`/${slug}/suites/${suiteId}`).then((r) => r.data)

// Script revisions (nested under a suite)
export const listRevisions = (slug, suiteId) => api.get(`/${slug}/suites/${suiteId}/revisions`).then((r) => r.data)
export const createRevision = (slug, suiteId, payload) =>
  api.post(`/${slug}/suites/${suiteId}/revisions`, payload).then((r) => r.data)
export const getRevision = (slug, suiteId, revisionId) =>
  api.get(`/${slug}/suites/${suiteId}/revisions/${revisionId}`).then((r) => r.data)
export const publishRevision = (slug, suiteId, revisionId) =>
  api.post(`/${slug}/suites/${suiteId}/revisions/${revisionId}/publish`).then((r) => r.data)
export const cloneRevision = (slug, suiteId, revisionId, payload) =>
  api.post(`/${slug}/suites/${suiteId}/revisions/${revisionId}/clone`, payload).then((r) => r.data)

// Test cases (nested under a revision)
export const listCases = (slug, revisionId) => api.get(`/${slug}/revisions/${revisionId}/cases`).then((r) => r.data)
export const createCase = (slug, revisionId, payload) =>
  api.post(`/${slug}/revisions/${revisionId}/cases`, payload).then((r) => r.data)
export const updateCase = (slug, revisionId, caseId, payload) =>
  api.put(`/${slug}/revisions/${revisionId}/cases/${caseId}`, payload).then((r) => r.data)
export const deleteCase = (slug, revisionId, caseId) =>
  api.delete(`/${slug}/revisions/${revisionId}/cases/${caseId}`).then((r) => r.data)
export const caseExportUrl = (slug, revisionId) => `${API_BASE}/${slug}/revisions/${revisionId}/cases/export`
export const caseImportTemplateUrl = (slug, revisionId) =>
  `${API_BASE}/${slug}/revisions/${revisionId}/cases/import-template`
export const importCasesExcel = (slug, revisionId, file) => {
  const form = new FormData()
  form.append('file', file)
  return api
    .post(`/${slug}/revisions/${revisionId}/cases/import-excel`, form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    .then((r) => r.data)
}
export const importCasesCsv = (slug, revisionId, file) => {
  const form = new FormData()
  form.append('file', file)
  return api
    .post(`/${slug}/revisions/${revisionId}/cases/import-csv`, form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    .then((r) => r.data)
}

// Test cycles
export const listCycles = (slug, includeSystemGenerated = false) =>
  api.get(`/${slug}/cycles`, { params: { include_system_generated: includeSystemGenerated } }).then((r) => r.data)
export const createCycle = (slug, payload) => api.post(`/${slug}/cycles`, payload).then((r) => r.data)
export const getCycle = (slug, cycleId) => api.get(`/${slug}/cycles/${cycleId}`).then((r) => r.data)
export const updateCycle = (slug, cycleId, payload) => api.put(`/${slug}/cycles/${cycleId}`, payload).then((r) => r.data)
export const lockCycle = (slug, cycleId) => api.post(`/${slug}/cycles/${cycleId}/lock`).then((r) => r.data)
export const reopenCycle = (slug, cycleId, reason) =>
  api.post(`/${slug}/cycles/${cycleId}/reopen`, { reason }).then((r) => r.data)
export const rerunCycle = (slug, cycleId, mode, caseIds) =>
  api.post(`/${slug}/cycles/${cycleId}/rerun`, { mode, case_ids: caseIds }).then((r) => r.data)

// Quick Manual Test entry flow
export const createQuickTest = (slug, payload) => api.post(`/${slug}/quick-test`, payload).then((r) => r.data)
export const runSuiteNow = (slug, suiteId, revisionId, payload = {}) =>
  api.post(`/${slug}/suites/${suiteId}/revisions/${revisionId}/run-now`, payload).then((r) => r.data)
export const getContinueLastTest = (slug) => api.get(`/${slug}/continue-last-test`).then((r) => r.data)

// Cycle test results (execution)
export const listCycleResults = (slug, cycleId) => api.get(`/${slug}/cycles/${cycleId}/results`).then((r) => r.data)
export const getCycleResult = (slug, cycleId, resultId) =>
  api.get(`/${slug}/cycles/${cycleId}/results/${resultId}`).then((r) => r.data)
export const updateCycleResult = (slug, cycleId, resultId, payload) =>
  api.put(`/${slug}/cycles/${cycleId}/results/${resultId}`, payload).then((r) => r.data)
export const reviewCycleResult = (slug, cycleId, resultId, payload) =>
  api.post(`/${slug}/cycles/${cycleId}/results/${resultId}/review`, payload).then((r) => r.data)
export const getCycleResultHistory = (slug, cycleId, resultId) =>
  api.get(`/${slug}/cycles/${cycleId}/results/${resultId}/history`).then((r) => r.data)

// Evidence
export const listEvidence = (slug, cycleId, resultId) =>
  api.get(`/${slug}/cycles/${cycleId}/results/${resultId}/evidence`).then((r) => r.data)
export const uploadEvidence = (slug, cycleId, resultId, blob, { evidenceType, caption, filename, workflowRunId, workflowStepRunId }) => {
  const form = new FormData()
  form.append('file', blob, filename || 'evidence.png')
  form.append('evidence_type', evidenceType)
  if (caption) form.append('caption', caption)
  if (workflowRunId != null) form.append('workflow_run_id', String(workflowRunId))
  if (workflowStepRunId != null) form.append('workflow_step_run_id', String(workflowStepRunId))
  return api
    .post(`/${slug}/cycles/${cycleId}/results/${resultId}/evidence`, form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    .then((r) => r.data)
}
export const evidenceOriginalUrl = (slug, cycleId, resultId, evidenceId) =>
  `${API_BASE}/${slug}/cycles/${cycleId}/results/${resultId}/evidence/${evidenceId}/original`
export const archiveEvidence = (slug, cycleId, resultId, evidenceId) =>
  api.put(`/${slug}/cycles/${cycleId}/results/${resultId}/evidence/${evidenceId}/archive`).then((r) => r.data)

// Annotations
export const listAnnotations = (slug, cycleId, resultId, evidenceId) =>
  api.get(`/${slug}/cycles/${cycleId}/results/${resultId}/evidence/${evidenceId}/annotations`).then((r) => r.data)
export const createAnnotation = (slug, cycleId, resultId, evidenceId, payload) =>
  api
    .post(`/${slug}/cycles/${cycleId}/results/${resultId}/evidence/${evidenceId}/annotations`, payload)
    .then((r) => r.data)

// Dashboard
export const getDashboard = (slug) => api.get(`/${slug}/dashboard`).then((r) => r.data)

// Reports
export const getExecutionSummary = (slug, cycleId) =>
  api.get(`/${slug}/reports/execution-summary`, { params: { cycle_id: cycleId } }).then((r) => r.data)
export const getDetailedResults = (slug, cycleId, filters = {}) =>
  api.get(`/${slug}/reports/detailed-results`, { params: { cycle_id: cycleId, ...filters } }).then((r) => r.data)
export const getNgDefects = (slug, cycleId) =>
  api.get(`/${slug}/reports/ng-defects`, { params: { cycle_id: cycleId } }).then((r) => r.data)
export const getEvidenceCompletenessReport = (slug, cycleId) =>
  api.get(`/${slug}/reports/evidence-completeness`, { params: { cycle_id: cycleId } }).then((r) => r.data)
export const getRevisionComparison = (slug, revisionAId, revisionBId) =>
  api.get(`/${slug}/reports/revision-comparison`, { params: { revision_a_id: revisionAId, revision_b_id: revisionBId } }).then((r) => r.data)
export const getCycleComparison = (slug, cycleAId, cycleBId) =>
  api.get(`/${slug}/reports/cycle-comparison`, { params: { cycle_a_id: cycleAId, cycle_b_id: cycleBId } }).then((r) => r.data)
export const getTesterProgress = (slug, cycleId) =>
  api.get(`/${slug}/reports/tester-progress`, { params: { cycle_id: cycleId } }).then((r) => r.data)
export const getGoLiveReadinessReport = (slug, cycleId) =>
  api.get(`/${slug}/reports/go-live-readiness`, { params: { cycle_id: cycleId } }).then((r) => r.data)
export const getSignoffSummary = (slug, cycleId) =>
  api.get(`/${slug}/reports/signoff-summary`, { params: { cycle_id: cycleId } }).then((r) => r.data)
export const getStorageUsageReport = (slug) => api.get(`/${slug}/reports/storage-usage`).then((r) => r.data)

// Hybrid dashboard/reports/timing (HYB-5) — never touches the Track A
// endpoints above; separate prefix, separate formulas.
export const getHybridDashboard = (slug) => api.get(`/${slug}/hybrid-reports/dashboard`).then((r) => r.data)
export const getHybridLocatorFailures = (slug) => api.get(`/${slug}/hybrid-reports/locator-failures`).then((r) => r.data)
export const getHybridFailureCategories = (slug) => api.get(`/${slug}/hybrid-reports/failure-categories`).then((r) => r.data)
export const getHybridFrequentFailures = (slug) => api.get(`/${slug}/hybrid-reports/workflows-frequent-failures`).then((r) => r.data)
export const getHybridSlowestSteps = (slug) => api.get(`/${slug}/hybrid-reports/slowest-steps`).then((r) => r.data)
export const getRunTiming = (slug, runId) => api.get(`/${slug}/hybrid-reports/timing/runs/${runId}`).then((r) => r.data)
export const getRunDurationTrend = (slug, workflowId, limit = 50) =>
  api.get(`/${slug}/hybrid-reports/timing/run-trend`, { params: { workflow_id: workflowId, limit } }).then((r) => r.data)
export const getStepDurationTrend = (slug, workflowId, stepDescription, limit = 50) =>
  api
    .get(`/${slug}/hybrid-reports/timing/step-trend`, { params: { workflow_id: workflowId, step_description: stepDescription, limit } })
    .then((r) => r.data)

// Defects
export const listDefects = (slug, cycleId) => api.get(`/${slug}/defects`, { params: { cycle_id: cycleId } }).then((r) => r.data)
export const createDefect = (slug, payload) => api.post(`/${slug}/defects`, payload).then((r) => r.data)
export const updateDefect = (slug, defectId, payload) => api.put(`/${slug}/defects/${defectId}`, payload).then((r) => r.data)

// Sign-offs
export const listSignoffs = (slug, cycleId) => api.get(`/${slug}/cycles/${cycleId}/signoffs`).then((r) => r.data)
export const createSignoff = (slug, cycleId, payload) => api.post(`/${slug}/cycles/${cycleId}/signoffs`, payload).then((r) => r.data)

// Export
export const exportExcelUrl = (slug, cycleId) => `${API_BASE}/${slug}/cycles/${cycleId}/export/excel`
export const exportZipUrl = (slug, cycleId) => `${API_BASE}/${slug}/cycles/${cycleId}/export/zip`

// Workflows (HYB-1)
export const listWorkflows = (slug) => api.get(`/${slug}/workflows`).then((r) => r.data)
export const createWorkflow = (slug, payload) => api.post(`/${slug}/workflows`, payload).then((r) => r.data)
export const deleteWorkflow = (slug, workflowId) => api.delete(`/${slug}/workflows/${workflowId}`)
export const getWorkflow = (slug, workflowId) => api.get(`/${slug}/workflows/${workflowId}`).then((r) => r.data)
export const listWorkflowRevisions = (slug, workflowId) =>
  api.get(`/${slug}/workflows/${workflowId}/revisions`).then((r) => r.data)
export const createWorkflowRevision = (slug, workflowId, payload) =>
  api.post(`/${slug}/workflows/${workflowId}/revisions`, payload).then((r) => r.data)
export const getWorkflowRevision = (slug, workflowId, revisionId) =>
  api.get(`/${slug}/workflows/${workflowId}/revisions/${revisionId}`).then((r) => r.data)
export const publishWorkflowRevision = (slug, workflowId, revisionId) =>
  api.post(`/${slug}/workflows/${workflowId}/revisions/${revisionId}/publish`).then((r) => r.data)
export const cloneWorkflowRevision = (slug, workflowId, revisionId, payload) =>
  api.post(`/${slug}/workflows/${workflowId}/revisions/${revisionId}/clone`, payload).then((r) => r.data)
export const listWorkflowSteps = (slug, workflowId, revisionId) =>
  api.get(`/${slug}/workflows/${workflowId}/revisions/${revisionId}/steps`).then((r) => r.data)
export const createWorkflowStep = (slug, workflowId, revisionId, payload) =>
  api.post(`/${slug}/workflows/${workflowId}/revisions/${revisionId}/steps`, payload).then((r) => r.data)
export const updateWorkflowStep = (slug, workflowId, revisionId, stepId, payload) =>
  api.put(`/${slug}/workflows/${workflowId}/revisions/${revisionId}/steps/${stepId}`, payload).then((r) => r.data)
export const deleteWorkflowStep = (slug, workflowId, revisionId, stepId) =>
  api.delete(`/${slug}/workflows/${workflowId}/revisions/${revisionId}/steps/${stepId}`).then((r) => r.data)
export const reorderWorkflowSteps = (slug, workflowId, revisionId, stepIdsInOrder) =>
  api
    .post(`/${slug}/workflows/${workflowId}/revisions/${revisionId}/steps/reorder`, { step_ids_in_order: stepIdsInOrder })
    .then((r) => r.data)
export const listWorkflowLinks = (slug, workflowId, revisionId) =>
  api.get(`/${slug}/workflows/${workflowId}/revisions/${revisionId}/links`).then((r) => r.data)
export const createWorkflowLink = (slug, workflowId, revisionId, testCaseId) =>
  api.post(`/${slug}/workflows/${workflowId}/revisions/${revisionId}/links`, { test_case_id: testCaseId }).then((r) => r.data)
export const deleteWorkflowLink = (slug, workflowId, revisionId, linkId) =>
  api.delete(`/${slug}/workflows/${workflowId}/revisions/${revisionId}/links/${linkId}`).then((r) => r.data)

// Workflow runs (HYB-2)
export const listWorkflowRuns = (slug) => api.get(`/${slug}/workflow-runs`).then((r) => r.data)
export const queueWorkflowRun = (slug, workflowRevisionId, cycleTestResultId = null) =>
  api
    .post(`/${slug}/workflow-runs`, { workflow_revision_id: workflowRevisionId, cycle_test_result_id: cycleTestResultId })
    .then((r) => r.data)
export const prepareBrowserWorkflowRun = (slug, workflowRevisionId) =>
  api.post(`/${slug}/workflow-runs/browser-prepare`, { workflow_revision_id: workflowRevisionId }).then((r) => r.data)
export const getWorkflowRun = (slug, runId) => api.get(`/${slug}/workflow-runs/${runId}`).then((r) => r.data)
export const workflowRunScreenshotUrl = (slug, runId, screenshotId) =>
  `${API_BASE}/${slug}/workflow-runs/${runId}/screenshots/${screenshotId}`
export const cancelWorkflowRun = (slug, runId) => api.post(`/${slug}/workflow-runs/${runId}/cancel`).then((r) => r.data)
// Phase E: "Test It Now" -- runs a DRAFT revision without publishing it.
// Never counted in reports/export (see backend hybrid_metrics.py).
export const previewWorkflowRun = (slug, workflowRevisionId) =>
  api.post(`/${slug}/workflow-runs/preview`, { workflow_revision_id: workflowRevisionId }).then((r) => r.data)

// Manual checkpoints (HYB-4)
export const getCheckpointContext = (slug, runId, workflowStepId) =>
  api.get(`/${slug}/workflow-runs/${runId}/checkpoint`, { params: { workflow_step_id: workflowStepId } }).then((r) => r.data)
export const listCheckpointDecisions = (slug, runId, workflowStepId = null) =>
  api
    .get(`/${slug}/workflow-runs/${runId}/checkpoint-decisions`, { params: workflowStepId ? { workflow_step_id: workflowStepId } : {} })
    .then((r) => r.data)
export const submitCheckpointDecision = (slug, runId, payload) =>
  api.post(`/${slug}/workflow-runs/${runId}/checkpoint-decision`, payload).then((r) => r.data)
export const reviewCheckpointDecision = (slug, runId, decisionId, reviewStatus) =>
  api.post(`/${slug}/workflow-runs/${runId}/checkpoint-decisions/${decisionId}/review`, { review_status: reviewStatus }).then((r) => r.data)

// Runner tokens (HYB-2)
export const listRunnerTokens = () => api.get('/runner-tokens').then((r) => r.data)
export const getRunnerFleetStatus = () => api.get('/runner-tokens/status').then((r) => r.data)
export const createRunnerToken = (label) => api.post('/runner-tokens', { label }).then((r) => r.data)
export const revokeRunnerToken = (tokenId) => api.put(`/runner-tokens/${tokenId}/revoke`).then((r) => r.data)

// Recording sessions (HYB-3)
export const listRecordingSessions = (slug) => api.get(`/${slug}/recording-sessions`).then((r) => r.data)
export const createRecordingSession = (slug, workflowId, targetUrl) =>
  api.post(`/${slug}/recording-sessions`, { workflow_id: workflowId, target_url: targetUrl }).then((r) => r.data)
export const getRecordingSession = (slug, sessionId) => api.get(`/${slug}/recording-sessions/${sessionId}`).then((r) => r.data)
export const pauseRecordingSession = (slug, sessionId) => api.post(`/${slug}/recording-sessions/${sessionId}/pause`).then((r) => r.data)
export const resumeRecordingSession = (slug, sessionId) => api.post(`/${slug}/recording-sessions/${sessionId}/resume`).then((r) => r.data)
export const stopRecordingSession = (slug, sessionId) => api.post(`/${slug}/recording-sessions/${sessionId}/stop`).then((r) => r.data)
export const discardRecordingSession = (slug, sessionId) => api.post(`/${slug}/recording-sessions/${sessionId}/discard`).then((r) => r.data)
export const undoLastRecordedStep = (slug, sessionId) => api.post(`/${slug}/recording-sessions/${sessionId}/undo-last-step`).then((r) => r.data)
// ADR-HYB-002: mints the short-lived, session-scoped token the tester
// pastes into the Chrome extension popup -- never the tester's own JWT.
export const authorizeExtension = (slug, sessionId) => api.post(`/${slug}/recording-sessions/${sessionId}/authorize-extension`).then((r) => r.data)
export const insertRecordingCheckpoint = (slug, sessionId, checkpointInstructions) =>
  api.post(`/${slug}/recording-sessions/${sessionId}/insert-checkpoint`, { checkpoint_instructions: checkpointInstructions }).then((r) => r.data)
export const insertRecordingWait = (slug, sessionId, durationMs) =>
  api.post(`/${slug}/recording-sessions/${sessionId}/insert-wait`, { duration_ms: durationMs }).then((r) => r.data)
export const insertRecordingScreenshotAfter = (slug, sessionId, stepId) =>
  api.post(`/${slug}/recording-sessions/${sessionId}/steps/${stepId}/insert-screenshot-after`).then((r) => r.data)
export const updateRecordedStep = (slug, sessionId, stepId, payload) =>
  api.put(`/${slug}/recording-sessions/${sessionId}/steps/${stepId}`, payload).then((r) => r.data)
export const deleteRecordedStep = (slug, sessionId, stepId) =>
  api.delete(`/${slug}/recording-sessions/${sessionId}/steps/${stepId}`).then((r) => r.data)
export const reorderRecordedSteps = (slug, sessionId, stepIdsInOrder) =>
  api.post(`/${slug}/recording-sessions/${sessionId}/steps/reorder`, { step_ids_in_order: stepIdsInOrder }).then((r) => r.data)
export const requestLocatorTest = (slug, sessionId, stepId) =>
  api.post(`/${slug}/recording-sessions/${sessionId}/steps/${stepId}/test-locator`).then((r) => r.data)
export const saveRecordingAsDraft = (slug, sessionId, revisionLabel, changeSummary) =>
  api
    .post(`/${slug}/recording-sessions/${sessionId}/save-as-draft`, { revision_label: revisionLabel, change_summary: changeSummary })
    .then((r) => r.data)

export default api
