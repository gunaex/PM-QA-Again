export default function EmptyState({
  icon: Icon,
  title = 'Nothing here yet',
  description = '',
  actionLabel,
  onAction,
  className = '',
}) {
  return (
    <div className={`flex flex-col items-center justify-center py-16 text-center ${className}`}>
      {Icon && (
        <div className="w-16 h-16 rounded-full bg-gray-100 flex items-center justify-center mb-4">
          <Icon size={32} strokeWidth={1.5} className="text-gray-400" />
        </div>
      )}
      <h3 className="text-lg font-medium text-gray-900">{title}</h3>
      {description && <p className="mt-1 text-sm text-gray-500 max-w-sm">{description}</p>}
      {actionLabel && onAction && (
        <button
          onClick={onAction}
          className="mt-5 px-4 py-2 bg-emerald-600 text-white text-sm font-medium rounded-lg hover:bg-emerald-700 transition"
        >
          {actionLabel}
        </button>
      )}
    </div>
  )
}
