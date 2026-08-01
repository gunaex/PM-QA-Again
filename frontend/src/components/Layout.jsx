import { useEffect, useState } from 'react'
import { NavLink, Outlet, useParams } from 'react-router-dom'
import { getProject } from '../api/client'
import UserBadge from './UserBadge.jsx'

const tabClass = ({ isActive }) =>
  `px-4 py-2 rounded-md text-sm font-medium ${
    isActive ? 'bg-emerald-600 text-white' : 'text-gray-600 hover:bg-gray-100'
  }`

export default function Layout() {
  const { slug } = useParams()
  const [project, setProject] = useState(null)
  const [projectLoadError, setProjectLoadError] = useState(false)

  useEffect(() => {
    setProjectLoadError(false)
    getProject(slug)
      .then(setProject)
      .catch(() => setProjectLoadError(true))
  }, [slug])

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white border-b border-gray-200">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 py-4 flex flex-wrap items-center justify-between gap-x-4 gap-y-3">
          <div className="flex items-center gap-4 min-w-0">
            <NavLink to="/" className="text-sm text-gray-500 hover:text-gray-800 shrink-0">
              &larr; Projects
            </NavLink>
            <h1 className="text-lg font-semibold text-gray-900 truncate">{project?.name || slug}</h1>
          </div>
          <nav className="flex gap-2 flex-wrap">
            <NavLink to={`/${slug}/dashboard`} className={tabClass}>
              Dashboard
            </NavLink>
            <NavLink to={`/${slug}/suites`} className={tabClass}>
              Test Suites
            </NavLink>
            <NavLink to={`/${slug}/cycles`} className={tabClass}>
              Test Cycles
            </NavLink>
            <NavLink to={`/${slug}/reports`} className={tabClass}>
              Reports
            </NavLink>
            <NavLink to={`/${slug}/workflows`} className={tabClass}>
              Workflows
            </NavLink>
          </nav>
          <UserBadge />
        </div>
      </header>
      {projectLoadError && (
        <div className="bg-red-50 border-b border-red-200 text-red-700 text-sm text-center py-2">
          Could not reach the backend to load this project's details. Your data is safe — this page just
          couldn't connect. Try refreshing.
        </div>
      )}
      <main className="max-w-6xl mx-auto px-4 sm:px-6 py-6">
        <Outlet context={{ project }} />
      </main>
    </div>
  )
}
