/**
 * 统一 API 客户端
 * - 使用相对路径，开发环境由 Vite proxy 转发，生产环境由 Nginx 转发
 * - 自动携带认证 Token，401 时自动踢回登录页
 */
import axios, { type AxiosInstance } from 'axios'

export const TOKEN_KEY = 'das_token'
export const USER_KEY = 'das_user'

export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) || ''
}

export function setAuth(token: string, username: string) {
  localStorage.setItem(TOKEN_KEY, token)
  localStorage.setItem(USER_KEY, username)
}

export function clearAuth() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
}

export function getStoredUser(): string {
  return localStorage.getItem(USER_KEY) || ''
}

/** 401 时回调（由 App.vue 注册，切回登录页） */
let onUnauthorized: (() => void) | null = null
export function registerUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn
}

export const http: AxiosInstance = axios.create({ timeout: 120000 })

http.interceptors.request.use((config) => {
  const token = getToken()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

http.interceptors.response.use(
  (res) => res,
  (error) => {
    if (error.response?.status === 401 && onUnauthorized) {
      clearAuth()
      onUnauthorized()
    }
    return Promise.reject(error)
  },
)

/** 后端接口封装（与原后端契约完全一致） */
export const api = {
  /** 启动智能体任务 */
  startTask: (query: string, threadId: string) =>
    http.post('/api/task', { query, thread_id: threadId }),

  /** 上传文件 */
  uploadFiles: (files: File[], threadId: string) => {
    const fd = new FormData()
    fd.append('thread_id', threadId)
    files.forEach((f) => fd.append('files', f))
    return http.post('/api/upload', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },

  /** 列出会话输出文件 */
  listFiles: (path: string) =>
    http.get<{ files: FileMeta[]; error?: string }>('/api/files', { params: { path } }),

  /** 构造文件下载链接（走下载接口；<a href> 带不了请求头，令牌只能进 query） */
  downloadUrl: (absPath: string) =>
    `/api/download?path=${encodeURIComponent(absPath)}&token=${encodeURIComponent(getToken())}`,
}

export interface FileMeta {
  name: string
  type: string
  path: string
  size: number
  mtime: number
}

/** 认证接口（独立 auth 微服务，Nginx 挂在 /api/auth 下） */
export const authApi = {
  register: (username: string, password: string) =>
    http.post('/api/auth/register', { username, password }),

  login: (username: string, password: string) =>
    http.post<{ token: string; username: string }>('/api/auth/login', { username, password }),

  me: () => http.get<{ username: string }>('/api/auth/me'),

  logout: () => http.post('/api/auth/logout'),
}
