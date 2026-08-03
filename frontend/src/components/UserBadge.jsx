import { useNavigate } from 'react-router-dom'
import { User, LogOut } from 'lucide-react'
import { useAuth } from '../auth/AuthContext.jsx'

export default function UserBadge() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  if (!user) return null

  const handleLogout = async () => {
    await logout()
    navigate('/login', { replace: true })
  }

  return (
    <div className="flex items-center gap-3 text-sm shrink-0">
      <span className="text-gray-500 flex items-center gap-1.5">
        <User size={14} />
        {user.email} <span className="text-gray-400">({user.role})</span>
      </span>
      <button onClick={handleLogout} className="text-emerald-600 hover:text-emerald-800 font-medium flex items-center gap-1 transition">
        <LogOut size={14} />
        Log out
      </button>
    </div>
  )
}
