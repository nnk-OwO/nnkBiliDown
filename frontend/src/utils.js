export function formatBytes(n) {
  if (!n || Number.isNaN(Number(n))) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let v = Number(n)
  let i = 0
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i += 1
  }
  return `${v.toFixed(v >= 100 || i === 0 ? 0 : 1)} ${units[i]}`
}

export function formatSpeed(n) {
  return `${formatBytes(n)}/s`
}

export function formatDuration(sec) {
  if (!sec || Number.isNaN(Number(sec))) return '--:--'
  let s = Math.round(Number(sec))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  s = s % 60
  const mm = h > 0 ? String(m).padStart(2, '0') : String(m)
  return `${h > 0 ? `${h}:` : ''}${mm}:${String(s).padStart(2, '0')}`
}

export function formatEta(eta) {
  if (eta == null || Number.isNaN(Number(eta))) return '--'
  let s = Math.round(Number(eta))
  if (s <= 0) return '即将完成'
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  s = s % 60
  if (h > 0) return `${h}时${m}分`
  if (m > 0) return `${m}分${s}秒`
  return `${s}秒`
}

export const STATUS_META = {
  queued: { label: '排队中', cls: 'bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-200' },
  downloading: { label: '下载中', cls: 'bg-pink-100 text-pink-600 dark:bg-pink-500/15 dark:text-pink-300' },
  completed: { label: '已完成', cls: 'bg-emerald-100 text-emerald-600 dark:bg-emerald-500/15 dark:text-emerald-300' },
  failed: { label: '失败', cls: 'bg-red-100 text-red-600 dark:bg-red-500/15 dark:text-red-300' },
  cancelled: { label: '已取消', cls: 'bg-amber-100 text-amber-600 dark:bg-amber-500/15 dark:text-amber-300' },
}

export function isBiliUrl(text) {
  return /(bilibili\.com|b23\.tv|bili2233\.cn)/i.test(text || '')
}
