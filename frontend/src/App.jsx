import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, proxyImage, wsUrl } from './api.js'
import CookieModal from './components/CookieModal.jsx'
import Header from './components/Header.jsx'
import SettingsModal from './components/SettingsModal.jsx'
import TaskCard from './components/TaskCard.jsx'
import Toasts from './components/Toasts.jsx'
import { CheckIcon, DownloadIcon, HistoryIcon, LinkIcon, PlayIcon, SearchIcon, WarnIcon } from './components/Icons.jsx'
import { formatDuration, isBiliUrl } from './utils.js'

const inputCls =
  'w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-800 placeholder:text-slate-300 focus:border-pink-400 focus:ring-4 focus:ring-pink-100 dark:border-white/10 dark:bg-white/5 dark:text-white dark:placeholder:text-slate-500 dark:focus:ring-pink-500/20'

function App() {
  const [health, setHealth] = useState(null)
  const [settings, setSettings] = useState(null)
  const [cookieStatus, setCookieStatus] = useState({ has_cookie: false, logged_in: false, user: null })
  const [tasks, setTasks] = useState([])
  const [url, setUrl] = useState('')
  const [batchMode, setBatchMode] = useState(false)
  const [batchText, setBatchText] = useState('')
  const [parsing, setParsing] = useState(false)
  const [parseResult, setParseResult] = useState(null)
  const [selectedPages, setSelectedPages] = useState(() => new Set())
  const [selectedQuality, setSelectedQuality] = useState(null)
  const [selectedCodec, setSelectedCodec] = useState('auto')
  const [downloadOptions, setDownloadOptions] = useState({ output_format: 'mp4', download_subtitles: false, download_danmaku: false, download_thumbnail: false })
  const [creating, setCreating] = useState(false)
  const [showSettings, setShowSettings] = useState(false)
  const [showCookie, setShowCookie] = useState(false)
  const [tab, setTab] = useState('queue')
  const [toasts, setToasts] = useState([])
  const [theme, setTheme] = useState(() => localStorage.getItem('bilidl-theme') || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'))
  const initialRef = useRef(false)
  const lastClipboardRef = useRef('')
  const lastAutoParsedRef = useRef('')

  const toast = useCallback((message, type = 'success') => {
    const id = `${Date.now()}-${Math.random()}`
    setToasts((t) => [...t, { id, message, type }])
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), type === 'error' ? 6500 : 3500)
  }, [])

  // 主题
  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark')
    localStorage.setItem('bilidl-theme', theme)
  }, [theme])

  // 初始数据 + 书签工具跳转的 ?url=
  useEffect(() => {
    if (initialRef.current) return
    initialRef.current = true
    Promise.all([api.health(), api.settings(), api.cookieStatus(), api.tasks()])
      .then(([h, s, c, t]) => {
        setHealth(h)
        setSettings(s)
        setCookieStatus(c)
        setTasks(t.tasks || [])
        if (h?.ffmpeg && !h.ffmpeg.ok) toast('未检测到 ffmpeg，将无法合并高画质音视频', 'warn')
        const params = new URLSearchParams(window.location.search)
        const initialUrl = params.get('url')
        if (initialUrl) {
          setUrl(initialUrl)
          doParse(initialUrl, s)
        }
      })
      .catch((e) => toast(e.message, 'error'))
  }, [toast])

  // WebSocket 实时进度
  useEffect(() => {
    let ws
    let closed = false
    let timer
    function connect() {
      if (closed) return
      ws = new WebSocket(wsUrl())
      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          if (data.type === 'tasks_snapshot') {
            setTasks(data.tasks || [])
          } else if (data.type === 'task_update') {
            setTasks((prev) => {
              const idx = prev.findIndex((t) => t.id === data.task.id)
              if (idx === -1) return [data.task, ...prev]
              const next = [...prev]
              next[idx] = { ...next[idx], ...data.task }
              return next
            })
          } else if (data.type === 'task_deleted') {
            setTasks((prev) => prev.filter((t) => t.id !== data.id))
          }
        } catch {
          /* ignore */
        }
      }
      ws.onclose = () => {
        if (!closed) timer = setTimeout(connect, 2000)
      }
      ws.onerror = () => ws?.close()
    }
    connect()
    return () => {
      closed = true
      clearTimeout(timer)
      ws?.close()
    }
  }, [])

  // 粘贴/输入 URL 后自动解析（可在设置中关闭）
  useEffect(() => {
    if (!settings?.auto_parse_on_paste || !isBiliUrl(url) || !url.trim()) return undefined
    if (url.trim() === lastAutoParsedRef.current) return undefined
    const t = setTimeout(() => {
      lastAutoParsedRef.current = url.trim()
      doParse(url, settings, true)
    }, 900)
    return () => clearTimeout(t)
  }, [url, settings?.auto_parse_on_paste])

  // 页面重新获得焦点时自动读取剪贴板中的 B 站链接
  useEffect(() => {
    function onFocus() {
      if (!settings?.auto_parse_on_paste) return
      if (!navigator.clipboard?.readText) return
      navigator.clipboard
        .readText()
        .then((text) => {
          if (isBiliUrl(text) && text !== lastClipboardRef.current) {
            lastClipboardRef.current = text
            const m = text.match(/https?:\/\/[^\s'"<>]+/)
            const found = m ? m[0] : text.trim()
            setUrl((old) => (old === found ? old : found))
            toast('已从剪贴板读取 B 站链接')
          }
        })
        .catch(() => {})
    }
    window.addEventListener('focus', onFocus)
    return () => window.removeEventListener('focus', onFocus)
  }, [settings?.auto_parse_on_paste, toast])

  function initSelections(info, currentSettings) {
    const options = info?.quality_options || []
    const available = options.filter((o) => o.available)
    let quality = available[0] || options[0] || null
    const pref = currentSettings?.default_quality
    if (pref && pref !== 'best') {
      quality =
        available.find((o) => String(o.quality) === String(pref)) ||
        options.find((o) => String(o.quality) === String(pref)) ||
        quality
    }
    setSelectedQuality(quality)
    const group = quality || {}
    const codes = group.codecs || []
    const prefCodec = currentSettings?.preferred_codec || 'auto'
    setSelectedCodec(codes.some((c) => c.value === prefCodec) ? prefCodec : 'auto')
    const isBulk = info?.type === 'space' || info?.type === 'favorite'
    const limit = isBulk ? 50 : 2000
    setSelectedPages(new Set((info?.pages || []).slice(0, limit).map((p) => p.index)))
    setDownloadOptions((d) => ({
      ...d,
      output_format: currentSettings?.output_format || 'mp4',
      download_subtitles: !!currentSettings?.download_subtitles,
      download_danmaku: !!currentSettings?.download_danmaku,
      download_thumbnail: !!currentSettings?.download_thumbnail,
    }))
  }

  const doParse = useCallback(
    async (rawUrl, currentSettings, silent = false) => {
      const target = (rawUrl || '').trim()
      if (!target || !isBiliUrl(target)) return
      setParsing(true)
      if (!silent) setParseResult(null)
      try {
        lastAutoParsedRef.current = target
        const info = await api.parse(target)
        setParseResult(info)
        initSelections(info, currentSettings || settings)
        const account = info.account
        if (account && !account.is_login) {
          const unlocked = info.quality_options?.some((o) => !o.available && (o.requires_login || o.requires_vip))
          if (unlocked) toast('游客画质有限，登录后可以解锁更高清晰度', 'warn')
        }
      } catch (e) {
        setParseResult(null)
        toast(e.message, 'error')
      } finally {
        setParsing(false)
      }
    },
    [settings, toast],
  )

  async function refreshCookie() {
    try {
      const c = await api.cookieStatus()
      setCookieStatus(c)
      return c
    } catch (e) {
      toast(e.message, 'error')
      return null
    }
  }

  async function saveSettings(patch) {
    try {
      const s = await api.saveSettings(patch)
      setSettings(s)
      toast('设置已保存')
      setShowSettings(false)
    } catch (e) {
      toast(e.message, 'error')
      throw e
    }
  }

  async function addTasks() {
    if (batchMode) {
      if (!batchText.trim()) return toast('请粘贴一个或多个 B 站链接', 'error')
      setCreating(true)
      try {
        const res = await api.createTasks({
          batch_text: batchText,
          quality: selectedQuality?.quality ?? null,
          codec: selectedCodec,
          output_format: downloadOptions.output_format,
          download_subtitles: downloadOptions.download_subtitles,
          download_danmaku: downloadOptions.download_danmaku,
          download_thumbnail: downloadOptions.download_thumbnail,
        })
        toast(`已添加 ${res.created} 个下载任务`)
        setTab('queue')
      } catch (e) {
        toast(e.message, 'error')
      } finally {
        setCreating(false)
      }
      return
    }
    if (!parseResult) return toast('请先解析视频', 'error')
    if (selectedQuality && !selectedQuality.available) return toast('当前清晰度不可下载，请选择可用档位', 'error')
    setCreating(true)
    try {
      const indexes = [...selectedPages].sort((a, b) => a - b)
      const res = await api.createTasks({
        url: parseResult.url,
        page_indexes: indexes,
        quality: selectedQuality?.quality ?? null,
        codec: selectedCodec,
        output_format: downloadOptions.output_format,
        download_subtitles: downloadOptions.download_subtitles,
        download_danmaku: downloadOptions.download_danmaku,
        download_thumbnail: downloadOptions.download_thumbnail,
      })
      toast(`已添加 ${res.created} 个下载任务`)
      setTab('queue')
    } catch (e) {
      toast(e.message, 'error')
    } finally {
      setCreating(false)
    }
  }

  async function handleTaskAction(fn, okMsg) {
    try {
      await fn()
      if (okMsg) toast(okMsg)
    } catch (e) {
      toast(e.message, 'error')
    }
  }

  const togglePage = (index) => {
    setSelectedPages((prev) => {
      const next = new Set(prev)
      if (next.has(index)) next.delete(index)
      else next.add(index)
      return next
    })
  }

  const pages = parseResult?.pages || []
  const qualityOptions = parseResult?.quality_options || []
  const qualityOption = qualityOptions.find((o) => o.quality === selectedQuality?.quality) || selectedQuality
  const codecOptions = qualityOption?.codecs || []
  const codecOption = codecOptions.find((c) => c.value === selectedCodec) || codecOptions.find((c) => c.available) || { label: '自动' }

  const stats = useMemo(() => {
    const active = tasks.filter((t) => t.status === 'downloading' || t.status === 'queued').length
    const done = tasks.filter((t) => t.status === 'completed').length
    const failed = tasks.filter((t) => t.status === 'failed').length
    return { active, done, failed, total: tasks.length }
  }, [tasks])

  const visibleTasks = useMemo(() => {
    if (tab === 'history') return tasks
    return tasks.filter((t) => ['queued', 'downloading', 'completed', 'failed'].includes(t.status))
  }, [tasks, tab])

  return (
    <div className="bg-app min-h-screen text-slate-800 dark:text-slate-100">
      <Header
        cookieStatus={cookieStatus}
        theme={theme}
        onToggleTheme={() => setTheme((t) => (t === 'dark' ? 'light' : 'dark'))}
        onOpenCookie={() => setShowCookie(true)}
        onOpenSettings={() => setShowSettings(true)}
      />

      <main className="mx-auto max-w-6xl space-y-5 px-4 py-5 sm:px-6 sm:py-7">
        {health && !health.ffmpeg?.ok && (
          <div className="card flex items-start gap-3 border-amber-200 bg-amber-50/80 p-4 dark:border-amber-500/30 dark:bg-amber-500/10">
            <WarnIcon size={20} className="mt-0.5 shrink-0 text-amber-500" />
            <div className="text-sm text-amber-700 dark:text-amber-200">
              <b>未检测到 ffmpeg。</b> 下载 DASH 高清视频时无法合并音视频。{health.ffmpeg?.hint || '请安装 ffmpeg 并加入 PATH。'}
            </div>
          </div>
        )}

        {/* URL 输入区 */}
        <section className="card p-4 sm:p-5">
          <div className="mb-3 flex items-center justify-between gap-2">
            <div className="flex items-center gap-2 text-sm font-semibold">
              <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-pink-50 text-pink-500 dark:bg-pink-500/10"><LinkIcon size={15} /></span>
              粘贴 B 站链接
            </div>
            <label className="flex cursor-pointer items-center gap-1.5 text-xs text-slate-400">
              <input type="checkbox" checked={!!settings?.auto_parse_on_paste} onChange={(e) => saveSettings({ auto_parse_on_paste: e.target.checked }).catch(() => {})} className="h-3.5 w-3.5 accent-pink-500" />
              粘贴后自动解析
            </label>
          </div>

          {!batchMode ? (
            <div className="flex flex-col gap-2.5 sm:flex-row">
              <div className="relative flex-1">
                <SearchIcon size={17} className="absolute left-4 top-1/2 -translate-y-1/2 text-slate-300 dark:text-slate-500" />
                <input
                  className={`${inputCls} pl-11`}
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  placeholder="https://www.bilibili.com/video/BVxxxxxxxx 或 b23.tv 短链 / ep / ss / UP主空间 / 收藏夹"
                  onKeyDown={(e) => e.key === 'Enter' && doParse(url)}
                />
              </div>
              <button
                onClick={() => doParse(url)}
                disabled={parsing || !isBiliUrl(url)}
                className="flex h-12 items-center justify-center gap-2 rounded-2xl bg-gradient-to-r from-pink-500 to-rose-500 px-7 text-sm font-bold text-white shadow-lg shadow-pink-500/25 transition hover:brightness-105 active:scale-[0.98] disabled:opacity-50 disabled:shadow-none"
              >
                <SearchIcon size={17} className={parsing ? 'animate-pulse' : ''} />
                {parsing ? '解析中…' : '解析视频'}
              </button>
            </div>
          ) : (
            <div className="space-y-2.5">
              <textarea
                rows={5}
                className={inputCls}
                value={batchText}
                onChange={(e) => setBatchText(e.target.value)}
                placeholder={'批量下载：每行一个链接（支持 BV、b23.tv、ep/ss、UP 主空间、收藏夹）\n\nhttps://www.bilibili.com/video/BV...\nhttps://b23.tv/...\nhttps://www.bilibili.com/bangumi/play/ep...'}
              />
              <div className="text-[11px] text-slate-400">批量模式下会对每个链接的所有分P/剧集创建任务；如需挑选分P请使用单链接解析。</div>
            </div>
          )}

          <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <button
                onClick={() => setBatchMode((v) => !v)}
                className="rounded-xl bg-slate-100 px-3 py-1.5 text-xs font-medium text-slate-600 transition hover:bg-slate-200 dark:bg-white/5 dark:text-slate-300 dark:hover:bg-white/10"
              >
                {batchMode ? '← 返回单链接解析' : '批量 URL 输入'}
              </button>
              {parseResult && (
                <span className="hidden text-[11px] text-slate-400 sm:inline">
                  上次解析：{parseResult.title}
                </span>
              )}
            </div>
            {parseResult?.account && (
              <div className="text-xs text-slate-400">
                {parseResult.account.is_login ? (
                  <span className="text-emerald-500">账号 {parseResult.account.uname} · {parseResult.account.vip_status ? '大会员' : '普通会员'}</span>
                ) : (
                  <span>游客模式 · 登录可解锁更高画质</span>
                )}
              </div>
            )}
          </div>
        </section>

        {/* 解析结果 */}
        {parseResult && (
          <section className="card overflow-hidden">
            <div className="flex flex-col gap-4 p-4 sm:flex-row sm:p-5">
              <div className="relative h-44 w-full shrink-0 overflow-hidden rounded-xl bg-slate-100 dark:bg-white/5 sm:h-36 sm:w-60">
                {parseResult.cover ? (
                  <img src={proxyImage(parseResult.cover)} alt="" className="h-full w-full object-cover" />
                ) : (
                  <div className="flex h-full items-center justify-center text-slate-300"><PlayIcon size={32} /></div>
                )}
                <span className="absolute left-2 top-2 rounded-lg bg-black/60 px-2 py-1 text-[11px] font-medium text-white backdrop-blur">
                  {parseResult.type === 'bangumi' ? '番剧' : parseResult.type === 'space' ? 'UP 投稿' : parseResult.type === 'favorite' ? '收藏夹' : '视频'}
                </span>
              </div>
              <div className="min-w-0 flex-1">
                <h2 className="text-base font-bold leading-snug text-slate-900 dark:text-white sm:text-lg">{parseResult.title}</h2>
                <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-400">
                  <span>UP：{parseResult.uploader || '--'}</span>
                  <span>时长：{formatDuration(parseResult.duration)}</span>
                  <span>分P/条目：{pages.length}</span>
                  {parseResult.pages?.[0]?.ep_id ? <span>ep_id: {parseResult.pages[0].ep_id}</span> : null}
                </div>
                {parseResult.description && (
                  <p className="mt-2 line-clamp-2 text-xs leading-relaxed text-slate-400">{parseResult.description}</p>
                )}
                <div className="mt-3 flex items-center gap-2 text-xs">
                  {qualityOptions.some((o) => o.available && o.requires_login) ? (
                    <span className="rounded-full bg-emerald-50 px-2.5 py-1 font-medium text-emerald-600 dark:bg-emerald-500/10 dark:text-emerald-300">✓ 高画质已解锁</span>
                  ) : (
                    <span className="rounded-full bg-slate-100 px-2.5 py-1 font-medium text-slate-500 dark:bg-white/10 dark:text-slate-300">
                      {parseResult.account?.is_login ? '当前账号可用档位如下' : '游客档位如下，登录后可解锁更多'}
                    </span>
                  )}
                  <span className="text-slate-400">{qualityOptions.filter((o) => o.available).length} 个档位当前可下载</span>
                </div>
              </div>
            </div>

            <div className="grid grid-cols-1 gap-5 border-t border-slate-100 p-4 dark:border-white/10 sm:p-5 lg:grid-cols-5">
              <div className="space-y-4 lg:col-span-3">
                <div>
                  <div className="mb-2 text-xs font-semibold text-slate-500 dark:text-slate-300">清晰度</div>
                  <div className="flex flex-wrap gap-2">
                    {qualityOptions.map((o) => {
                      const selected = selectedQuality?.quality === o.quality
                      const locked = !o.available
                      return (
                        <button
                          key={o.quality}
                          disabled={locked}
                          onClick={() => {
                            setSelectedQuality(o)
                            const hasCodec = (o.codecs || []).some((c) => c.value === selectedCodec)
                            if (!hasCodec) setSelectedCodec((o.codecs || []).find((c) => c.available)?.value || 'auto')
                          }}
                          className={`relative rounded-xl px-3.5 py-2 text-sm font-medium transition ${
                            selected
                              ? 'bg-pink-500 text-white shadow-lg shadow-pink-500/25'
                              : locked
                                ? 'cursor-not-allowed bg-slate-50 text-slate-300 dark:bg-white/5 dark:text-slate-600'
                                : 'bg-slate-100 text-slate-700 hover:bg-pink-50 hover:text-pink-600 dark:bg-white/5 dark:text-slate-200 dark:hover:bg-pink-500/10'
                          }`}
                        >
                          <span className="mr-1">{o.label}</span>
                          {locked && (
                            <span className="absolute -right-1.5 -top-1.5 rounded-full bg-slate-200 px-1.5 py-0.5 text-[9px] font-bold text-slate-500 dark:bg-slate-700 dark:text-slate-300">
                              {o.requires_vip ? '大会员' : o.requires_login ? '需登录' : '不可用'}
                            </span>
                          )}
                        </button>
                      )
                    })}
                  </div>
                  <div className="mt-1.5 text-[11px] text-slate-400">
                    灰色 = 当前账号不可下载；登录或开通大会员后重新解析可解锁。
                  </div>
                </div>

                <div>
                  <div className="mb-2 text-xs font-semibold text-slate-500 dark:text-slate-300">视频编码</div>
                  <div className="flex flex-wrap gap-2">
                    {codecOptions.map((c) => (
                      <button
                        key={c.value}
                        disabled={c.available === false}
                        onClick={() => setSelectedCodec(c.value)}
                        className={`rounded-xl px-3.5 py-2 text-sm font-medium transition ${
                          selectedCodec === c.value
                            ? 'bg-sky-500 text-white shadow-lg shadow-sky-500/25'
                            : c.available === false
                              ? 'cursor-not-allowed bg-slate-50 text-slate-300 dark:bg-white/5 dark:text-slate-600'
                              : 'bg-slate-100 text-slate-700 hover:bg-sky-50 hover:text-sky-600 dark:bg-white/5 dark:text-slate-200 dark:hover:bg-sky-500/10'
                        }`}
                      >
                        {c.label}
                      </button>
                    ))}
                  </div>
                  <div className="mt-1.5 text-[11px] text-slate-400">MP4 推荐 AVC；MKV 可选 HEVC/AV1。当前选择：{codecOption?.label}</div>
                </div>

                <div>
                  <div className="mb-2 text-xs font-semibold text-slate-500 dark:text-slate-300">附加下载</div>
                  <div className="flex flex-wrap gap-x-5 gap-y-2">
                    {[
                      ['download_subtitles', 'CC 字幕'],
                      ['download_danmaku', '弹幕 XML'],
                      ['download_thumbnail', '封面图'],
                    ].map(([key, label]) => (
                      <label key={key} className="flex cursor-pointer items-center gap-2 text-sm text-slate-600 dark:text-slate-300">
                        <input type="checkbox" checked={!!downloadOptions[key]} onChange={(e) => setDownloadOptions((d) => ({ ...d, [key]: e.target.checked }))} className="h-4 w-4 accent-pink-500" />
                        {label}
                      </label>
                    ))}
                  </div>
                </div>
              </div>

              <div className="lg:col-span-2">
                <div className="mb-2 flex items-center justify-between">
                  <div className="text-xs font-semibold text-slate-500 dark:text-slate-300">选择要下载的分P / 剧集</div>
                  <div className="flex gap-2 text-xs font-medium text-pink-500">
                    <button onClick={() => setSelectedPages(new Set(pages.map((p) => p.index)))}>全选</button>
                    <button onClick={() => setSelectedPages(new Set())} className="text-slate-400 hover:text-slate-500">清空</button>
                  </div>
                </div>
                <div className="max-h-64 space-y-1 overflow-y-auto pr-1">
                  {pages.map((p) => {
                    const checked = selectedPages.has(p.index)
                    return (
                      <button
                        key={p.index}
                        onClick={() => togglePage(p.index)}
                        className={`flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left transition ${
                          checked ? 'bg-pink-50 dark:bg-pink-500/10' : 'hover:bg-slate-50 dark:hover:bg-white/5'
                        }`}
                      >
                        <span className={`flex h-4 w-4 shrink-0 items-center justify-center rounded border ${checked ? 'border-pink-500 bg-pink-500 text-white' : 'border-slate-300 dark:border-slate-600'}`}>
                          {checked && <CheckIcon size={11} />}
                        </span>
                        <span className="w-8 shrink-0 text-[11px] font-medium text-slate-400">P{p.index}</span>
                        <span className="min-w-0 flex-1 truncate text-xs text-slate-700 dark:text-slate-200">{p.part}</span>
                        <span className="shrink-0 text-[11px] text-slate-400">{formatDuration(p.duration)}</span>
                      </button>
                    )
                  })}
                </div>
                <div className="mt-2 text-[11px] text-slate-400">已选 {selectedPages.size} / {pages.length}</div>
              </div>
            </div>

            <div className="flex flex-col items-stretch gap-3 border-t border-slate-100 px-4 py-4 dark:border-white/10 sm:flex-row sm:items-center sm:justify-between sm:px-5">
              <div className="flex flex-wrap items-center gap-3">
                <label className="text-xs text-slate-500">
                  输出格式
                  <select
                    value={downloadOptions.output_format}
                    onChange={(e) => setDownloadOptions((d) => ({ ...d, output_format: e.target.value }))}
                    className="ml-2 rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-xs font-medium dark:border-white/10 dark:bg-white/5"
                  >
                    <option value="mp4">MP4</option>
                    <option value="mkv">MKV</option>
                  </select>
                </label>
                <span className="text-xs text-slate-400">将下载选中 {selectedPages.size} 项 · {selectedQuality?.label || '自动'} · {codecOption?.label || '自动'}</span>
              </div>
              <button
                onClick={addTasks}
                disabled={creating || selectedPages.size === 0}
                className="flex h-12 items-center justify-center gap-2 rounded-2xl bg-gradient-to-r from-pink-500 to-rose-500 px-8 text-sm font-bold text-white shadow-xl shadow-pink-500/30 transition hover:brightness-105 active:scale-[0.98] disabled:opacity-50 disabled:shadow-none"
              >
                <DownloadIcon size={18} />
                {creating ? '正在创建…' : `开始下载（${selectedPages.size}）`}
              </button>
            </div>
          </section>
        )}

        <section className="card p-4 sm:p-5">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <button
                onClick={() => setTab('queue')}
                className={`flex items-center gap-1.5 rounded-xl px-3 py-2 text-sm font-semibold transition ${tab === 'queue' ? 'bg-pink-50 text-pink-600 dark:bg-pink-500/10 dark:text-pink-300' : 'text-slate-400 hover:bg-slate-50 dark:hover:bg-white/5'}`}
              >
                <DownloadIcon size={15} /> 下载队列
              </button>
              <button
                onClick={() => setTab('history')}
                className={`flex items-center gap-1.5 rounded-xl px-3 py-2 text-sm font-semibold transition ${tab === 'history' ? 'bg-pink-50 text-pink-600 dark:bg-pink-500/10 dark:text-pink-300' : 'text-slate-400 hover:bg-slate-50 dark:hover:bg-white/5'}`}
              >
                <HistoryIcon size={15} /> 历史记录
              </button>
            </div>
            <div className="flex flex-wrap gap-2 text-[11px]">
              <span className="rounded-full bg-pink-50 px-2.5 py-1 font-medium text-pink-500 dark:bg-pink-500/10">进行中 {stats.active}</span>
              <span className="rounded-full bg-emerald-50 px-2.5 py-1 font-medium text-emerald-500 dark:bg-emerald-500/10">已完成 {stats.done}</span>
              <span className="rounded-full bg-red-50 px-2.5 py-1 font-medium text-red-400 dark:bg-red-500/10">失败 {stats.failed}</span>
              <span className="rounded-full bg-slate-100 px-2.5 py-1 font-medium text-slate-400 dark:bg-white/10">共 {stats.total}</span>
            </div>
          </div>

          {visibleTasks.length === 0 ? (
            <div className="flex flex-col items-center gap-2 py-14 text-center">
              <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-slate-100 text-slate-300 dark:bg-white/5 dark:text-slate-600">
                <DownloadIcon size={26} />
              </div>
              <div className="text-sm font-medium text-slate-400">暂无下载任务</div>
              <div className="text-xs text-slate-300 dark:text-slate-600">解析视频后点击“开始下载”，任务会实时出现在这里</div>
            </div>
          ) : (
            <div className="space-y-2.5">
              {visibleTasks.map((task) => (
                <TaskCard
                  key={task.id}
                  task={task}
                  onRetry={(id) => handleTaskAction(() => api.retry(id), '已重新加入队列')}
                  onCancel={(id) => handleTaskAction(() => api.cancel(id), '已发送取消请求')}
                  onDelete={(id, deleteFile) => handleTaskAction(() => api.remove(id, deleteFile), deleteFile ? '记录和文件已删除' : '记录已删除')}
                  onOpenFolder={(id) => handleTaskAction(() => api.openFolder(id))}
                />
              ))}
            </div>
          )}
        </section>

        <footer className="pb-4 text-center text-[11px] leading-relaxed text-slate-300 dark:text-slate-600">
          本工具仅用于个人学习与研究，请遵守相关法律法规和 B 站服务条款，勿用于商业用途或传播未授权内容。
          <br />Cookie 仅保存在本机（~/.nnkbilidown，权限 0600），服务端日志不会输出完整 Cookie。
        </footer>
      </main>

      <SettingsModal open={showSettings} settings={settings} health={health} onClose={() => setShowSettings(false)} onSave={saveSettings} />
      <CookieModal open={showCookie} cookieStatus={cookieStatus} onClose={() => setShowCookie(false)} onChanged={refreshCookie} />
      <Toasts toasts={toasts} onClose={(id) => setToasts((t) => t.filter((x) => x.id !== id))} />
    </div>
  )
}

export default App
