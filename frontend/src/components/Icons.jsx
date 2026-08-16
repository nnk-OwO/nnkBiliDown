export function Icon({ d, size = 20, className = '' }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
    >
      <path d={d} />
    </svg>
  )
}

const paths = {
  settings:
    'M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Zm7.4-3a7.4 7.4 0 0 0-.1-1.2l2-1.6-2-3.4-2.4 1a7.6 7.6 0 0 0-2-1.2L14.5 3h-5l-.4 3.1a7.6 7.6 0 0 0-2 1.2l-2.4-1-2 3.4 2 1.6a7.4 7.4 0 0 0 0 2.4l-2 1.6 2 3.4 2.4-1a7.6 7.6 0 0 0 2 1.2l.4 3.1h5l.4-3.1a7.6 7.6 0 0 0 2-1.2l2.4 1 2-3.4-2-1.6c.1-.4.1-.8.1-1.2Z',
  cookie: 'M12 3a9 9 0 1 0 9 9c0-.7-.1-1.3-.2-2A7 7 0 0 1 13 2.2 9 9 0 0 0 12 3Z',
  download: 'M12 3v12m0 0 4-4m-4 4-4-4M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2',
  trash: 'M4 7h16M9 7V4h6v3m3 0-1 13H7L6 7m4 4v5m4-5v5',
  refresh: 'M20 11a8 8 0 1 0-2.3 6.3M20 4v7h-7',
  folder: 'M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z',
  close: 'M6 6l12 12M18 6 6 18',
  moon: 'M21 12.8A9 9 0 1 1 11.2 3 7 7 0 0 0 21 12.8Z',
  sun: 'M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10Zm0-15v2m0 16v2M2 12h2m16 0h2M4.9 4.9l1.4 1.4m11.4 11.4 1.4 1.4m0-14.2-1.4 1.4M6.3 17.7l-1.4 1.4',
  link: 'M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.5 1.5M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7L12 19',
  check: 'm5 12 4 4L19 6',
  x: 'M18 6 6 18M6 6l12 12',
  play: 'm7 4 13 8-13 8V4Z',
  warn: 'M12 9v4m0 4h.01M10.3 3.7 2.5 17a2 2 0 0 0 1.7 3h15.6a2 2 0 0 0 1.7-3L13.7 3.7a2 2 0 0 0-3.4 0Z',
  search: 'm21 21-4.3-4.3M17 10.5a6.5 6.5 0 1 1-13 0 6.5 6.5 0 0 1 13 0Z',
  history: 'M3 12a9 9 0 1 0 3-6.7M3 4v5h5m4 3 4 4m0-8v4h-4',
}

export function SettingsIcon(props) { return <Icon d={paths.settings} {...props} /> }
export function CookieIcon(props) { return <Icon d={paths.cookie} {...props} /> }
export function DownloadIcon(props) { return <Icon d={paths.download} {...props} /> }
export function TrashIcon(props) { return <Icon d={paths.trash} {...props} /> }
export function RefreshIcon(props) { return <Icon d={paths.refresh} {...props} /> }
export function FolderIcon(props) { return <Icon d={paths.folder} {...props} /> }
export function CloseIcon(props) { return <Icon d={paths.close} {...props} /> }
export function MoonIcon(props) { return <Icon d={paths.moon} {...props} /> }
export function SunIcon(props) { return <Icon d={paths.sun} {...props} /> }
export function LinkIcon(props) { return <Icon d={paths.link} {...props} /> }
export function CheckIcon(props) { return <Icon d={paths.check} {...props} /> }
export function XIcon(props) { return <Icon d={paths.x} {...props} /> }
export function PlayIcon(props) { return <Icon d={paths.play} {...props} /> }
export function WarnIcon(props) { return <Icon d={paths.warn} {...props} /> }
export function SearchIcon(props) { return <Icon d={paths.search} {...props} /> }
export function HistoryIcon(props) { return <Icon d={paths.history} {...props} /> }
