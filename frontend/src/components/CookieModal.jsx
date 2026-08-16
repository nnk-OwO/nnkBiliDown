import { useEffect, useRef, useState } from 'react'
import { api } from '../api.js'
import { CloseIcon, CookieIcon, RefreshIcon } from './Icons.jsx'

const inputCls =
  'w-full rounded-xl border border-slate-200 bg-white px-3 py-2 font-mono text-[11px] leading-relaxed text-slate-700 placeholder:text-slate-300 focus:border-pink-400 focus:ring-2 focus:ring-pink-100 dark:border-white/10 dark:bg-white/5 dark:text-slate-200 dark:focus:ring-pink-500/20'

export default function CookieModal({ open, cookieStatus, onClose, onChanged }) {
  const [cookie, setCookie] = useState('')
  const [testing, setTesting] = useState(false)
  const [clearing, setClearing] = useState(false)
  const [error, setError] = useState('')
  const [qr, setQr] = useState(null)
  const [qrLoading, setQrLoading] = useState(false)
  const [qrMessage, setQrMessage] = useState('')
  const timerRef = useRef(null)

  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [])

  if (!open) return null

  async function handleTest(save = true) {
    if (!cookie.trim()) return setError('请先粘贴 Cookie')
    setTesting(true)
    setError('')
    try {
      const res = await api.testCookie(cookie.trim(), save)
      await onChanged()
      setCookie('')
      return res
    } catch (e) {
      setError(e.message)
      throw e
    } finally {
      setTesting(false)
    }
  }

  async function handleClear() {
    setClearing(true)
    try {
      await api.clearCookie()
      setError('')
      await onChanged()
    } catch (e) {
      setError(e.message)
    } finally {
      setClearing(false)
    }
  }

  async function startQr() {
    setQrLoading(true)
    setError('')
    setQrMessage('正在生成二维码…')
    try {
      const data = await api.qrGenerate()
      setQr(data)
      setQrMessage(data.url ? '' : '请使用 B 站 App 扫码')
      pollQr(data.qrcode_key)
    } catch (e) {
      setError(e.message)
    } finally {
      setQrLoading(false)
    }
  }

  function pollQr(key) {
    const poll = async () => {
      try {
        const res = await api.qrStatus(key)
        setQrMessage(res.message || '')
        if (res.status === 'success') {
          setQr(null)
          await onChanged()
          return
        }
        if (res.status !== 'expired') {
          timerRef.current = setTimeout(poll, 2000)
        } else {
          setQr(null)
        }
      } catch (e) {
        setError(e.message)
        setQr(null)
      }
    }
    timerRef.current = setTimeout(poll, 1200)
  }

  const loggedIn = cookieStatus?.logged_in

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-slate-950/45 backdrop-blur-sm sm:items-center sm:p-4" onMouseDown={onClose}>
      <div
        className="max-h-[92vh] w-full max-w-xl overflow-y-auto rounded-t-2xl bg-white p-5 shadow-2xl dark:bg-slate-900 sm:rounded-2xl sm:p-6"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="mb-5 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-bold text-slate-900 dark:text-white">账号登录</h2>
            <p className="text-xs text-slate-400">登录后可下载 720P/1080P，大会员可解锁 4K/高码率</p>
          </div>
          <button onClick={onClose} className="rounded-full p-2 text-slate-400 hover:bg-slate-100 dark:hover:bg-white/10">
            <CloseIcon size={18} />
          </button>
        </div>

        <div className="mb-4 flex items-center justify-between rounded-xl bg-slate-50 p-3 dark:bg-white/5">
          <div className="flex items-center gap-2 text-sm">
            <CookieIcon size={16} className={loggedIn ? 'text-emerald-500' : 'text-slate-400'} />
            {loggedIn ? (
              <span className="text-slate-700 dark:text-slate-200">
                已登录：<b>{cookieStatus.user?.uname || 'B 站用户'}</b>（UID {cookieStatus.user?.mid || '--'}）
                {cookieStatus.user?.vip_status ? <span className="ml-1 text-xs text-pink-500">大会员</span> : null}
              </span>
            ) : (
              <span className="text-slate-500">未登录（游客最高通常为 480P）</span>
            )}
          </div>
          {loggedIn && (
            <button onClick={handleClear} disabled={clearing} className="text-xs font-medium text-red-500 hover:text-red-600 disabled:opacity-50">
              {clearing ? '清除中…' : '清除 Cookie'}
            </button>
          )}
        </div>

        <div className="mb-1.5 text-xs font-medium text-slate-600 dark:text-slate-300">粘贴浏览器 Cookie</div>
        <textarea
          rows={4}
          className={inputCls}
          value={cookie}
          onChange={(e) => setCookie(e.target.value)}
          placeholder="在浏览器登录 bilibili.com 后，F12 → 网络/应用 → 复制完整 Cookie（至少包含 SESSDATA）"
        />
        <div className="mt-1 text-[11px] leading-relaxed text-slate-400">
          Cookie 只保存在本机 <code className="rounded bg-slate-100 px-1 dark:bg-white/10">~/.nnkbilidown/config.json</code>（0600 权限），服务端日志不会输出完整 Cookie。
        </div>

        <div className="mt-3 flex gap-2">
          <button
            onClick={() => handleTest(true).catch(() => {})}
            disabled={testing}
            className="flex-1 rounded-xl bg-pink-500 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-pink-500/25 hover:bg-pink-600 disabled:opacity-60"
          >
            {testing ? '测试登录中…' : '测试并保存'}
          </button>
          <button
            onClick={() => handleTest(false).catch(() => {})}
            disabled={testing}
            className="rounded-xl bg-slate-100 px-4 py-2.5 text-sm font-medium text-slate-600 hover:bg-slate-200 disabled:opacity-60 dark:bg-white/5 dark:text-slate-300 dark:hover:bg-white/10"
          >
            仅测试
          </button>
        </div>

        <div className="my-5 flex items-center gap-3 text-[11px] text-slate-300 dark:text-slate-600">
          <div className="h-px flex-1 bg-slate-100 dark:bg-white/10" /> 或扫码登录（推荐） <div className="h-px flex-1 bg-slate-100 dark:bg-white/10" />
        </div>

        {!qr ? (
          <button
            onClick={startQr}
            disabled={qrLoading}
            className="flex w-full items-center justify-center gap-2 rounded-xl border border-dashed border-slate-300 py-3 text-sm font-medium text-slate-500 transition hover:border-pink-300 hover:text-pink-500 disabled:opacity-60 dark:border-white/15"
          >
            <RefreshIcon size={16} className={qrLoading ? 'animate-spin' : ''} />
            {qrLoading ? '生成中…' : '显示二维码登录'}
          </button>
        ) : (
          <div className="flex flex-col items-center">
            {qr.image ? (
              <img src={qr.image} alt="B 站登录二维码" className="h-52 w-52 rounded-xl border border-slate-100 bg-white p-2 dark:border-white/10" />
            ) : (
              <div className="flex h-52 w-52 flex-col items-center justify-center gap-2 rounded-xl bg-slate-100 p-3 text-center text-xs text-slate-500 dark:bg-white/5 dark:text-slate-400">
                <span>二维码图片生成失败</span>
                <a href={qr.url} target="_blank" rel="noreferrer" className="text-pink-500 underline">点此打开登录链接</a>
              </div>
            )}
            <div className="mt-2 text-sm font-medium text-slate-600 dark:text-slate-300">{qrMessage || '请使用 B 站 App 扫码'}</div>
            <button onClick={() => { setQr(null); if (timerRef.current) clearTimeout(timerRef.current) }} className="mt-1 text-xs text-slate-400 hover:text-slate-500">
              取消
            </button>
          </div>
        )}

        {error && <div className="mt-3 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-600 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">{error}</div>}

        <div className="mt-5 rounded-xl bg-slate-50 p-3 text-[11px] leading-relaxed text-slate-400 dark:bg-white/5">
          <b className="text-slate-500 dark:text-slate-300">如何获取 Cookie：</b>
          <br />1. 浏览器登录 bilibili.com → F12 打开开发者工具
          <br />2. 点击“网络”标签，刷新页面，任选一个 api.bilibili.com 请求
          <br />3. 在请求头中找到 <code>Cookie:</code> 整行值，复制到上方输入框
          <br />4. 注意：Cookie 等同于账号凭证，请勿分享给他人。
        </div>
      </div>
    </div>
  )
}
