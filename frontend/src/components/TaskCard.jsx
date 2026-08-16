import { useState } from 'react'
import { proxyImage } from '../api.js'
import { STATUS_META, formatBytes, formatEta, formatSpeed } from '../utils.js'
import { FolderIcon, PlayIcon, RefreshIcon, TrashIcon, XIcon } from './Icons.jsx'

export default function TaskCard({ task, onRetry, onCancel, onDelete, onOpenFolder }) {
  const [confirmDelete, setConfirmDelete] = useState(false)
  const meta = STATUS_META[task.status] || STATUS_META.failed
  const active = task.status === 'downloading' || task.status === 'queued'
  const progress = Math.max(0, Math.min(100, Number(task.progress || 0)))

  return (
    <div className={`card relative overflow-hidden p-3.5 sm:p-4 ${active ? 'ring-1 ring-pink-200 dark:ring-pink-500/30' : ''}`}>
      {active && (
        <div className="pointer-events-none absolute inset-x-0 top-0 h-0.5 bg-slate-100 dark:bg-white/10">
          <div className="progress-fill h-full bg-gradient-to-r from-pink-400 to-rose-400" style={{ width: `${progress}%` }} />
        </div>
      )}
      <div className="flex gap-3">
        <div className="relative h-16 w-28 shrink-0 overflow-hidden rounded-lg bg-slate-100 dark:bg-white/5 sm:h-20 sm:w-32">
          {task.cover ? (
            <img src={proxyImage(task.cover)} alt="" className="h-full w-full object-cover" loading="lazy" />
          ) : (
            <div className="flex h-full w-full items-center justify-center text-slate-300"><PlayIcon size={22} /></div>
          )}
          {task.page_index > 1 && (
            <span className="absolute bottom-1 right-1 rounded bg-black/65 px-1.5 py-0.5 text-[10px] font-medium text-white">
              P{task.page_index}
            </span>
          )}
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <div className="truncate text-sm font-semibold text-slate-800 dark:text-slate-100" title={task.video_title}>
                {task.video_title}
              </div>
              <div className="mt-0.5 truncate text-xs text-slate-400" title={task.page_title}>
                {task.page_index > 1 ? `P${task.page_index} · ` : ''}{task.page_title}
              </div>
            </div>
            <span className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium ${meta.cls}`}>{meta.label}</span>
          </div>

          <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-slate-400">
            <span className="rounded bg-slate-100 px-1.5 py-0.5 dark:bg-white/10">{task.quality_label || '自动'}</span>
            <span className="rounded bg-slate-100 px-1.5 py-0.5 uppercase dark:bg-white/10">{(task.codec || 'auto').toUpperCase()}</span>
            <span>{task.output_format?.toUpperCase()}</span>
            {task.uploader && <span className="truncate">UP: {task.uploader}</span>}
          </div>

          {active && (
            <div className="mt-2">
              <div className="h-1.5 overflow-hidden rounded-full bg-slate-100 dark:bg-white/10">
                <div
                  className="progress-fill h-full rounded-full bg-gradient-to-r from-pink-400 via-pink-500 to-rose-400"
                  style={{ width: `${progress}%` }}
                />
              </div>
              <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-slate-400">
                <span className="font-mono">{progress.toFixed(1)}%</span>
                <span>{task.stage || '等待中'}</span>
                {task.speed > 0 && <span>{formatSpeed(task.speed)}</span>}
                {task.status === 'downloading' && <span>剩余 {formatEta(task.eta)}</span>}
                <span>{formatBytes(task.downloaded_bytes)}{task.total_bytes ? ` / ${formatBytes(task.total_bytes)}` : ''}</span>
              </div>
            </div>
          )}

          {task.status === 'completed' && (
            <div className="mt-2 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-emerald-600 dark:text-emerald-400">
              <span>{formatBytes(task.downloaded_bytes || 0)}</span>
              {task.finished_at && <span>{task.finished_at}</span>}
              <span className="truncate text-slate-400" title={task.filepath}>📁 {task.filepath || '文件已保存'}</span>
            </div>
          )}
          {task.error && <div className="mt-1.5 line-clamp-2 text-[11px] text-red-500">{task.error}</div>}
        </div>
      </div>

      <div className="mt-2.5 flex flex-wrap items-center justify-end gap-1.5">
        {task.status === 'completed' && (
          <button
            onClick={() => onOpenFolder(task.id)}
            className="flex items-center gap-1.5 rounded-lg bg-emerald-50 px-2.5 py-1.5 text-xs font-medium text-emerald-600 hover:bg-emerald-100 dark:bg-emerald-500/10 dark:text-emerald-300 dark:hover:bg-emerald-500/20"
          >
            <FolderIcon size={14} /> 打开文件夹
          </button>
        )}
        {(task.status === 'failed' || task.status === 'cancelled') && (
          <button
            onClick={() => onRetry(task.id)}
            className="flex items-center gap-1.5 rounded-lg bg-slate-100 px-2.5 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-200 dark:bg-white/5 dark:text-slate-300 dark:hover:bg-white/10"
          >
            <RefreshIcon size={14} /> 重试
          </button>
        )}
        {active && (
          <button
            onClick={() => onCancel(task.id)}
            className="flex items-center gap-1.5 rounded-lg bg-amber-50 px-2.5 py-1.5 text-xs font-medium text-amber-600 hover:bg-amber-100 dark:bg-amber-500/10 dark:text-amber-300 dark:hover:bg-amber-500/20"
          >
            <XIcon size={14} /> 取消
          </button>
        )}
        {confirmDelete ? (
          <span className="flex items-center gap-1.5">
            <span className="text-xs text-slate-400">确认删除？</span>
            <button onClick={() => { onDelete(task.id, false); setConfirmDelete(false) }} className="rounded-lg bg-red-500 px-2.5 py-1.5 text-xs font-semibold text-white hover:bg-red-600">仅记录</button>
            {task.status === 'completed' && (
              <button onClick={() => { onDelete(task.id, true); setConfirmDelete(false) }} className="rounded-lg bg-red-600 px-2.5 py-1.5 text-xs font-semibold text-white hover:bg-red-700">连同文件</button>
            )}
            <button onClick={() => setConfirmDelete(false)} className="rounded-lg px-2 py-1.5 text-xs text-slate-400">取消</button>
          </span>
        ) : (
          <button
            onClick={() => setConfirmDelete(true)}
            className="flex items-center gap-1 rounded-lg px-2 py-1.5 text-xs text-slate-400 hover:bg-red-50 hover:text-red-500 dark:hover:bg-red-500/10"
            title="删除记录"
          >
            <TrashIcon size={14} />
          </button>
        )}
      </div>
    </div>
  )
}
