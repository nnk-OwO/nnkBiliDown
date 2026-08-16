import { CookieIcon, MoonIcon, SettingsIcon, SunIcon } from './Icons.jsx'

export default function Header({ cookieStatus, theme, onToggleTheme, onOpenCookie, onOpenSettings }) {
  const loggedIn = cookieStatus?.logged_in
  return (
    <header className="sticky top-0 z-30 border-b border-black/5 bg-white/75 backdrop-blur dark:border-white/10 dark:bg-slate-950/70">
      <div className="mx-auto flex h-16 max-w-6xl items-center gap-3 px-4 sm:px-6">
        <div className="flex items-center gap-2.5">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-pink-400 to-pink-600 text-white shadow-lg shadow-pink-500/25">
            <span className="text-lg font-black">N</span>
          </div>
          <div className="leading-tight">
            <div className="text-[15px] font-bold tracking-tight text-slate-900 dark:text-white">
              nnkBili<span className="text-pink-500">Down</span>
            </div>
            <div className="hidden text-[11px] text-slate-400 sm:block">本地 B 站视频下载</div>
          </div>
        </div>

        <div className="ml-auto flex items-center gap-2">
          <button
            onClick={onOpenCookie}
            className={`flex h-9 items-center gap-1.5 rounded-full px-3 text-xs font-medium transition ${
              loggedIn
                ? 'bg-emerald-50 text-emerald-600 ring-1 ring-emerald-200 hover:bg-emerald-100 dark:bg-emerald-500/10 dark:text-emerald-300 dark:ring-emerald-500/20'
                : 'bg-slate-100 text-slate-600 hover:bg-slate-200 dark:bg-white/5 dark:text-slate-300 dark:hover:bg-white/10'
            }`}
          >
            <CookieIcon size={15} />
            <span className="hidden sm:inline">
              {loggedIn ? (cookieStatus?.user?.uname || '已登录') : '登录账号'}
            </span>
            <span className="sm:hidden">{loggedIn ? '已登录' : '登录'}</span>
            <span className={`h-1.5 w-1.5 rounded-full ${loggedIn ? 'bg-emerald-500' : 'bg-slate-300 dark:bg-slate-600'}`} />
          </button>

          <button
            onClick={onToggleTheme}
            className="flex h-9 w-9 items-center justify-center rounded-full bg-slate-100 text-slate-600 transition hover:bg-slate-200 dark:bg-white/5 dark:text-slate-300 dark:hover:bg-white/10"
            title="切换亮/暗模式"
          >
            {theme === 'dark' ? <SunIcon size={17} /> : <MoonIcon size={17} />}
          </button>
          <button
            onClick={onOpenSettings}
            className="flex h-9 w-9 items-center justify-center rounded-full bg-slate-100 text-slate-600 transition hover:bg-slate-200 dark:bg-white/5 dark:text-slate-300 dark:hover:bg-white/10"
            title="设置"
          >
            <SettingsIcon size={17} />
          </button>
        </div>
      </div>
    </header>
  )
}
