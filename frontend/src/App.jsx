import { lazy, Suspense } from 'react'
import { Routes, Route } from 'react-router-dom'
import Layout from './components/Layout.jsx'
import { DetailSkeleton, CardSkeleton, DashboardSkeleton } from './components/PageSkeleton.jsx'
import LoginPage from './pages/LoginPage.jsx'
import RequireAuth from './auth/RequireAuth.jsx'

// Lazy-loaded pages for code splitting
const ProjectList = lazy(() => import('./pages/ProjectList.jsx'))
const Dashboard = lazy(() => import('./pages/Dashboard.jsx'))
const SuiteList = lazy(() => import('./pages/SuiteList.jsx'))
const SuiteDetail = lazy(() => import('./pages/SuiteDetail.jsx'))
const RevisionDetail = lazy(() => import('./pages/RevisionDetail.jsx'))
const CycleList = lazy(() => import('./pages/CycleList.jsx'))
const CycleExecution = lazy(() => import('./pages/CycleExecution.jsx'))
const ReportsPage = lazy(() => import('./pages/ReportsPage.jsx'))
const HybridReportsPage = lazy(() => import('./pages/HybridReportsPage.jsx'))
const WorkflowList = lazy(() => import('./pages/WorkflowList.jsx'))
const WorkflowDetail = lazy(() => import('./pages/WorkflowDetail.jsx'))
const RunnerList = lazy(() => import('./pages/RunnerList.jsx'))
const UsersPage = lazy(() => import('./pages/UsersPage.jsx'))

function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/"
        element={
          <RequireAuth>
            <Suspense fallback={<div className="min-h-screen bg-gray-50 flex items-center justify-center"><DashboardSkeleton /></div>}>
              <ProjectList />
            </Suspense>
          </RequireAuth>
        }
      />
      <Route
        path="/runners"
        element={
          <RequireAuth>
            <Suspense fallback={<div className="min-h-screen bg-gray-50 p-10"><CardSkeleton count={3} /></div>}>
              <RunnerList />
            </Suspense>
          </RequireAuth>
        }
      />
      <Route
        path="/users"
        element={
          <RequireAuth>
            <Suspense fallback={<div className="min-h-screen bg-gray-50 p-10"><DetailSkeleton /></div>}>
              <UsersPage />
            </Suspense>
          </RequireAuth>
        }
      />
      <Route
        path="/:slug"
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route index element={<Suspense fallback={<DashboardSkeleton />}><Dashboard /></Suspense>} />
        <Route path="dashboard" element={<Suspense fallback={<DashboardSkeleton />}><Dashboard /></Suspense>} />
        <Route path="suites" element={<Suspense fallback={<CardSkeleton count={6} />}><SuiteList /></Suspense>} />
        <Route path="suites/:suiteId" element={<Suspense fallback={<DetailSkeleton />}><SuiteDetail /></Suspense>} />
        <Route path="suites/:suiteId/revisions/:revisionId" element={<Suspense fallback={<DetailSkeleton />}><RevisionDetail /></Suspense>} />
        <Route path="cycles" element={<Suspense fallback={<CardSkeleton count={4} />}><CycleList /></Suspense>} />
        <Route path="cycles/:cycleId" element={<Suspense fallback={<DetailSkeleton />}><CycleExecution /></Suspense>} />
        <Route path="reports" element={<Suspense fallback={<DetailSkeleton />}><ReportsPage /></Suspense>} />
        <Route path="hybrid-reports" element={<Suspense fallback={<DashboardSkeleton />}><HybridReportsPage /></Suspense>} />
        <Route path="workflows" element={<Suspense fallback={<CardSkeleton count={3} />}><WorkflowList /></Suspense>} />
        <Route path="workflows/:workflowId" element={<Suspense fallback={<DetailSkeleton />}><WorkflowDetail /></Suspense>} />
      </Route>
    </Routes>
  )
}

export default App
