/** Shared skeleton loading patterns */

export function CardSkeleton({ count = 6 }) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="bg-white border border-gray-200 rounded-lg p-5 animate-pulse">
          <div className="h-5 bg-gray-200 rounded w-3/4 mb-3" />
          <div className="h-3 bg-gray-100 rounded w-1/2 mb-2" />
          <div className="h-3 bg-gray-100 rounded w-1/3" />
        </div>
      ))}
    </div>
  )
}

export function TableSkeleton({ rows = 5 }) {
  return (
    <div className="bg-white border border-gray-200 rounded-lg overflow-hidden animate-pulse">
      <div className="h-10 bg-gray-100" />
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="h-12 border-t border-gray-100 flex items-center px-4">
          <div className="h-3 bg-gray-200 rounded w-1/4 mr-8" />
          <div className="h-3 bg-gray-100 rounded w-1/3" />
        </div>
      ))}
    </div>
  )
}

export function DashboardSkeleton() {
  return (
    <div className="animate-pulse space-y-6">
      {/* KPI tiles */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="bg-white border border-gray-200 rounded-lg p-4">
            <div className="h-3 bg-gray-200 rounded w-1/2 mb-2" />
            <div className="h-8 bg-gray-100 rounded w-1/3" />
          </div>
        ))}
      </div>
      {/* Charts area */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="bg-white border border-gray-200 rounded-lg p-5 h-64">
          <div className="h-4 bg-gray-200 rounded w-1/3 mb-4" />
          <div className="h-4/5 bg-gray-100 rounded" />
        </div>
        <div className="bg-white border border-gray-200 rounded-lg p-5 h-64">
          <div className="h-4 bg-gray-200 rounded w-1/3 mb-4" />
          <div className="h-4/5 bg-gray-100 rounded" />
        </div>
      </div>
    </div>
  )
}

export function DetailSkeleton() {
  return (
    <div className="animate-pulse space-y-4">
      <div className="h-7 bg-gray-200 rounded w-1/3" />
      <div className="bg-white border border-gray-200 rounded-lg p-6 space-y-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="flex gap-4">
            <div className="h-4 bg-gray-200 rounded w-24 shrink-0" />
            <div className="h-4 bg-gray-100 rounded flex-1" />
          </div>
        ))}
      </div>
    </div>
  )
}
