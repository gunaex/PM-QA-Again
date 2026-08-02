import { Routes, Route } from 'react-router-dom'
import Layout from './components/Layout.jsx'
import ProjectList from './pages/ProjectList.jsx'
import Dashboard from './pages/Dashboard.jsx'
import SuiteList from './pages/SuiteList.jsx'
import SuiteDetail from './pages/SuiteDetail.jsx'
import RevisionDetail from './pages/RevisionDetail.jsx'
import CycleList from './pages/CycleList.jsx'
import CycleExecution from './pages/CycleExecution.jsx'
import ReportsPage from './pages/ReportsPage.jsx'
import HybridReportsPage from './pages/HybridReportsPage.jsx'
import WorkflowList from './pages/WorkflowList.jsx'
import WorkflowDetail from './pages/WorkflowDetail.jsx'
import RunnerList from './pages/RunnerList.jsx'
import UsersPage from './pages/UsersPage.jsx'
import LoginPage from './pages/LoginPage.jsx'
import RequireAuth from './auth/RequireAuth.jsx'

function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/"
        element={
          <RequireAuth>
            <ProjectList />
          </RequireAuth>
        }
      />
      <Route
        path="/runners"
        element={
          <RequireAuth>
            <RunnerList />
          </RequireAuth>
        }
      />
      <Route
        path="/users"
        element={
          <RequireAuth>
            <UsersPage />
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
        <Route index element={<Dashboard />} />
        <Route path="dashboard" element={<Dashboard />} />
        <Route path="suites" element={<SuiteList />} />
        <Route path="suites/:suiteId" element={<SuiteDetail />} />
        <Route path="suites/:suiteId/revisions/:revisionId" element={<RevisionDetail />} />
        <Route path="cycles" element={<CycleList />} />
        <Route path="cycles/:cycleId" element={<CycleExecution />} />
        <Route path="reports" element={<ReportsPage />} />
        <Route path="hybrid-reports" element={<HybridReportsPage />} />
        <Route path="workflows" element={<WorkflowList />} />
        <Route path="workflows/:workflowId" element={<WorkflowDetail />} />
      </Route>
    </Routes>
  )
}

export default App
