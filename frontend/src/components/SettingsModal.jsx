import { useEffect, useState } from 'react'
import { CloseIcon, LinkIcon, WarnIcon } from './Icons.jsx'

function Field({ label, hint, children }) {
  return (
    <label className="block">
      <div className="mb-1.5 text-xs font-medium text-slate-600 dark:text-slate-300">{label}</div>
      {children}
      {hint ? <div className="mt-1 text-[11px] leading-relaxed text-slate-400">{hint}</div> : null}
    </label>
  )
}

const inputCls =
  'w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 placeholder:text-slate-300 focus:border-pink-400 focus:ring-2 focus:ring-pink-100 dark:border-white/10 dark:bg-white/5 dark:text-white dark:placeholder:text-slate-500 dark:focus:ring-pink-500/20'

export default function SettingsModal({ open, settings, health, onClose, onSave }) {
  const [form, setForm] = useState(settings || {})
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (settings) setForm(settings)
  }, [settings, open])

  if (!open || !settings) return null

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }))
  const bookmarklet = `javascript:(function(){location.href='http://localhost:7860/?url='+encodeURIComponent(location.href)})()`

  async function submit(e) {
    e.preventDefault()
    setSaving(true)
    try {
      await onSave(form)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-slate-950/45 p-0 backdrop-blur-sm sm:items-center sm:p-4" onMouseDown={onClose}>
      <div
        className="max-h-[92vh] w-full max-w-2xl overflow-y-auto rounded-t-2xl bg-white p-5 shadow-2xl dark:bg-slate-900 sm:rounded-2xl sm:p-6"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="mb-5 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-bold text-slate-900 dark:text-white">设置</h2>
            <p className="text-xs text-slate-400">修改后自动保存到本机配置</p>
          </div>
          <button onClick={onClose} className="rounded-full p-2 text-slate-400 hover:bg-slate-100 dark:hover:bg-white/10">
            <CloseIcon size={18} />
          </button>
        </div>

        {health && !health.ffmpeg?.ok && (
          <div className="mb-5 flex gap-2.5 rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200">
            <WarnIcon size={16} className="mt-0.5 shrink-0" />
            <div>
              <b>未检测到 ffmpeg。</b>下载高画质 DASH 音视频需要它合并文件。安装方法：{health.ffmpeg?.hint || '请安装 ffmpeg 并加入 PATH'}
            </div>
          </div>
        )}

        <form onSubmit={submit} className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="sm:col-span-2">
            <Field label="下载目录" hint="建议使用剩余空间较大的磁盘路径">
              <input className={inputCls} value={form.download_dir || ''} onChange={(e) => set('download_dir', e.target.value)} />
            </Field>
          </div>
          <div className="sm:col-span-2">
            <Field label="文件名模板" hint={'可用字段：%(title)s、%(uploader)s、%(id)s、%(ext)s、%(upload_date)s 等。默认按 UP 主建子文件夹。'}>
              <input className={inputCls} value={form.filename_template || ''} onChange={(e) => set('filename_template', e.target.value)} />
            </Field>
          </div>
          <Field label="默认清晰度">
            <select className={inputCls} value={String(form.default_quality ?? 'best')} onChange={(e) => set('default_quality', e.target.value === 'best' ? 'best' : Number(e.target.value))}>
              <option value="best">最高可下载清晰度</option>
              <option value="127">8K</option>
              <option value="120">4K</option>
              <option value="116">1080P 60帧</option>
              <option value="112">1080P 高码率</option>
              <option value="80">1080P</option>
              <option value="64">720P</option>
              <option value="32">480P</option>
              <option value="16">360P</option>
            </select>
          </Field>
          <Field label="默认编码">
            <select className={inputCls} value={form.preferred_codec || 'auto'} onChange={(e) => set('preferred_codec', e.target.value)}>
              <option value="auto">自动（优先 AVC）</option>
              <option value="avc">AVC (H.264)</option>
              <option value="hevc">HEVC (H.265)</option>
              <option value="av1">AV1</option>
            </select>
          </Field>
          <Field label="输出格式">
            <select className={inputCls} value={form.output_format || 'mp4'} onChange={(e) => set('output_format', e.target.value)}>
              <option value="mp4">MP4（兼容性最好）</option>
              <option value="mkv">MKV（适合多轨/字幕）</option>
            </select>
          </Field>
          <Field label="并发下载数（1-3）">
            <select className={inputCls} value={form.max_concurrent || 2} onChange={(e) => set('max_concurrent', Number(e.target.value))}>
              {[1, 2, 3].map((n) => <option key={n} value={n}>{n} 个任务</option>)}
            </select>
          </Field>
          <div className="sm:col-span-2">
            <Field label="代理（可选）" hint="例如 http://127.0.0.1:7890，留空表示直连">
              <input className={inputCls} value={form.proxy || ''} onChange={(e) => set('proxy', e.target.value)} placeholder="http://127.0.0.1:7890" />
            </Field>
          </div>
          <div className="flex flex-wrap gap-x-5 gap-y-2 sm:col-span-2">
            {[
              ['download_subtitles', '默认下载 CC 字幕'],
              ['download_danmaku', '默认下载弹幕 XML'],
              ['download_thumbnail', '默认下载封面'],
              ['auto_parse_on_paste', '粘贴链接后自动解析'],
              ['auto_open_folder', '下载完成后打开文件夹'],
            ].map(([key, label]) => (
              <label key={key} className="flex cursor-pointer items-center gap-2 text-sm text-slate-700 dark:text-slate-200">
                <input type="checkbox" checked={!!form[key]} onChange={(e) => set(key, e.target.checked)} className="h-4 w-4 accent-pink-500" />
                {label}
              </label>
            ))}
          </div>

          <div className="sm:col-span-2">
            <div className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-slate-600 dark:text-slate-300">
              <LinkIcon size={13} /> 浏览器书签小工具
            </div>
            <div className="flex gap-2">
              <input readOnly className={`${inputCls} font-mono text-[11px]`} value={bookmarklet} onFocus={(e) => e.target.select()} />
              <button
                type="button"
                className="shrink-0 rounded-xl bg-slate-100 px-3 text-xs font-medium text-slate-600 hover:bg-slate-200 dark:bg-white/5 dark:text-slate-300 dark:hover:bg-white/10"
                onClick={() => navigator.clipboard?.writeText(bookmarklet)}
              >
                复制
              </button>
            </div>
            <p className="mt-1 text-[11px] text-slate-400">在 B 站视频页点击该书签，即可跳回本应用并自动解析当前页面。</p>
          </div>

          <div className="flex justify-end gap-2 pt-2 sm:col-span-2">
            <button type="button" onClick={onClose} className="rounded-xl px-4 py-2 text-sm font-medium text-slate-500 hover:bg-slate-100 dark:hover:bg-white/10">
              取消
            </button>
            <button disabled={saving} className="rounded-xl bg-pink-500 px-5 py-2 text-sm font-semibold text-white shadow-lg shadow-pink-500/25 hover:bg-pink-600 disabled:opacity-60">
              {saving ? '保存中…' : '保存设置'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
