import { CloseIcon, WarnIcon, CheckIcon } from './Icons.jsx'

export default function Toasts({ toasts, onClose }) {
  if (!toasts.length) return null
  return (
    <div className="pointer-events-none fixed left-1/2 top-4 z-[100] flex w-[min(92vw,420px)] -translate-x-1/2 flex-col gap-2">
      {toasts.map((t) => (
        <div
          key={t.id}
          className={`pointer-events-auto flex items-start gap-2.5 rounded-xl border px-4 py-3 text-sm shadow-xl backdrop-blur transition-all ${
            t.type === 'error'
              ? 'border-red-200 bg-red-50/95 text-red-700 dark:border-red-500/30 dark:bg-red-950/90 dark:text-red-200'
              : t.type === 'warn'
                ? 'border-amber-200 bg-amber-50/95 text-amber-700 dark:border-amber-500/30 dark:bg-amber-950/90 dark:text-amber-200'
                : 'border-emerald-200 bg-emerald-50/95 text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-950/90 dark:text-emerald-200'
          }`}
        >
          {t.type === 'error' ? <WarnIcon size={17} className="mt-0.5 shrink-0" /> : <CheckIcon size={17} className="mt-0.5 shrink-0" />}
          <div className="min-w-0 flex-1 break-words">{t.message}</div>
          <button onClick={() => onClose(t.id)} className="opacity-60 hover:opacity-100">
            <CloseIcon size={15} />
          </button>
        </div>
      ))}
    </div>
  )
}
