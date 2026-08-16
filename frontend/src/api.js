async function request(path, options = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  })
  let data = null
  try {
    data = await res.json()
  } catch {
    data = null
  }
  if (!res.ok) {
    const detail = data?.detail || `请求失败 (${res.status})`
    const err = new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
    err.status = res.status
    err.data = data
    throw err
  }
  return data
}

export const api = {
  health: () => request('/api/health'),
  settings: () => request('/api/settings'),
  saveSettings: (patch) => request('/api/settings', { method: 'PUT', body: JSON.stringify(patch) }),
  cookieStatus: () => request('/api/cookie/status'),
  testCookie: (cookie, save = true) =>
    request('/api/cookie/test', { method: 'POST', body: JSON.stringify({ cookie, save }) }),
  clearCookie: () => request('/api/cookie', { method: 'DELETE' }),
  parse: (url) => request('/api/video/parse', { method: 'POST', body: JSON.stringify({ url }) }),
  createTasks: (payload) => request('/api/tasks', { method: 'POST', body: JSON.stringify(payload) }),
  tasks: () => request('/api/tasks'),
  task: (id) => request(`/api/tasks/${id}`),
  retry: (id) => request(`/api/tasks/${id}/retry`, { method: 'POST' }),
  cancel: (id) => request(`/api/tasks/${id}/cancel`, { method: 'POST' }),
  remove: (id, deleteFile = false) =>
    request(`/api/tasks/${id}?delete_file=${deleteFile}`, { method: 'DELETE' }),
  openFolder: (id) => request(`/api/tasks/${id}/open-folder`, { method: 'POST' }),
  qrGenerate: () => request('/api/qr/generate'),
  qrStatus: (key) => request(`/api/qr/status?key=${encodeURIComponent(key)}`),
}

export function wsUrl() {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${window.location.host}/api/ws`
}

export function proxyImage(url) {
  if (!url) return ''
  if (url.startsWith('//')) url = `https:${url}`
  return `/api/proxy/image?url=${encodeURIComponent(url)}`
}
