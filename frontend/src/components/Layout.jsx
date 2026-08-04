import { useEffect, useState } from 'react'
import { NavLink, Outlet, useParams, useLocation } from 'react-router-dom'
import { LayoutDashboard, BookOpen, PlayCircle, BarChart3, Bot, Activity, ChevronLeft } from 'lucide-react'
import { getProject } from '../api/client'
import UserBadge from './UserBadge.jsx'

const tabs = [
  { to: 'dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { to: 'suites', label: 'Test Suites', icon: BookOpen },
  { to: 'cycles', label: 'Test Cycles', icon: PlayCircle },
  { to: 'reports', label: 'Reports', icon: BarChart3 },
  { to: 'workflows', label: 'Automated Tests', icon: Bot },
  { to: 'hybrid-reports', label: 'Hybrid Reports', icon: Activity },
]

export default function Layout() {
  const { slug } = useParams()
  const location = useLocation()
  const [project, setProject] = useState(null)
  const [projectLoadError, setProjectLoadError] = useState(false)

  useEffect(() => {
    setProjectLoadError(false)
    getProject(slug)
      .then(setProject)
      .catch(() => setProjectLoadError(true))
  }, [slug])

  // Build breadcrumb: split path, filter empties, build segments
  const segments = location.pathname.split('/').filter(Boolean).slice(1) // remove slug

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col">
      {/* Sticky header with backdrop blur */}
      <header className="sticky top-0 z-40 bg-white/80 backdrop-blur-sm border-b border-gray-200 shadow-sm">
        <div className="w-full px-4 sm:px-6 lg:px-8 2xl:px-10 py-3">
          {/* Top row: project name + nav */}
          <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
            <div className="flex items-center gap-3 min-w-0">
              <NavLink to="/" className="text-sm text-gray-500 hover:text-gray-800 shrink-0 flex items-center gap-1 transition">
                <ChevronLeft size={16} />
                Projects
              </NavLink>
              {project && (
                <h1 className="text-lg font-semibold text-gray-900 truncate">{project.name}</h1>
              )}
            </div>
            {/* Tab navigation */}
            <nav className="flex gap-1 overflow-x-auto pb-0.5 scrollbar-hide">
              {tabs.map(({ to, label, icon: Icon }) => {
                const fullPath = `/${slug}/${to}`
                const isActive = location.pathname === `/${slug}` ? to === 'dashboard' : location.pathname.startsWith(fullPath)
                return (
                  <NavLink
                    key={to}
                    to={`/${slug}/${to}`}
                    className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium transition whitespace-nowrap ${
                      isActive
                        ? 'bg-emerald-600 text-white shadow-sm'
                        : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
                    }`}
                  >
                    <Icon size={15} />
                    <span className="hidden sm:inline">{label}</span>
                  </NavLink>
                )
              })}
            </nav>
          </div>
        </div>
      </header>

      {projectLoadError && (
        <div className="bg-red-50 border-b border-red-200 text-red-700 text-sm text-center py-2">
          Could not reach the backend to load this project's details. Your data is safe — this page just
          couldn't connect. Try refreshing.
        </div>
      )}

      <main className="w-full flex-1 px-4 sm:px-6 lg:px-8 2xl:px-10 py-6">
        <Outlet context={{ project }} />
      </main>

      <footer className="w-full border-t border-gray-200 bg-white px-4 sm:px-6 lg:px-8 2xl:px-10 py-3 flex justify-end">
        <UserBadge />
      </footer>
    </div>
  )
}
