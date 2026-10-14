/** 共享类型与小工具 */

export interface LogItem {
  type: string
  title: string
  details: any
  timestamp: string
  /** 事件到达的毫秒时间戳（用于计算每步耗时） */
  ts?: number
}

export interface MsgFile {
  name: string
  path: string
  url: string
}

export interface Message {
  role: 'user' | 'ai' | 'system'
  content: string
  logs?: LogItem[]
  files?: MsgFile[]
  timestamp?: number
  /** 任务完成时刻，用于展示本条消息总耗时 */
  finishedAt?: number
}

/** 字节数 → 人类可读 */
export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`
}

/** 毫秒 → 1.2s / 1m12s（耗时展示统一走这里，数字等宽） */
export function formatDuration(ms: number): string {
  if (!isFinite(ms) || ms < 0) return '—'
  if (ms < 1000) return `${Math.round(ms)}ms`
  const s = ms / 1000
  if (s < 60) return `${s.toFixed(1)}s`
  const m = Math.floor(s / 60)
  const rest = Math.round(s % 60)
  return `${m}m${String(rest).padStart(2, '0')}s`
}

/** 相对时间：刚刚 / 3 分钟前 / 昨天 12:30 */
export function relativeTime(ts: number): string {
  const diff = Date.now() - ts
  if (diff < 60_000) return '刚刚'
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} 分钟前`
  const d = new Date(ts)
  const hh = String(d.getHours()).padStart(2, '0')
  const mm = String(d.getMinutes()).padStart(2, '0')
  const isToday = new Date().toDateString() === d.toDateString()
  if (isToday) return `今天 ${hh}:${mm}`
  const y = new Date(Date.now() - 86_400_000)
  if (y.toDateString() === d.toDateString()) return `昨天 ${hh}:${mm}`
  return `${d.getMonth() + 1}/${d.getDate()} ${hh}:${mm}`
}

/** 文件扩展名 → 图标 + 类型 + 色标 */
export function fileMeta(name: string): { icon: string; kind: string; tone: string } {
  const ext = name.split('.').pop()?.toLowerCase() || ''
  if (['md', 'txt'].includes(ext)) return { icon: '📝', kind: '文档', tone: '#5563ff' }
  if (ext === 'pdf') return { icon: '📕', kind: 'PDF', tone: '#dc2626' }
  if (['xlsx', 'xls', 'csv'].includes(ext)) return { icon: '📊', kind: '表格', tone: '#0f9d58' }
  if (['png', 'jpg', 'jpeg', 'gif', 'svg', 'webp'].includes(ext))
    return { icon: '🖼️', kind: '图片', tone: '#0891b2' }
  if (['doc', 'docx'].includes(ext)) return { icon: '📘', kind: 'Word', tone: '#2563eb' }
  if (['json', 'yml', 'yaml', 'xml'].includes(ext)) return { icon: '🧾', kind: '配置', tone: '#8b5cf6' }
  return { icon: '📄', kind: ext ? ext.toUpperCase() : '文件', tone: '#6b7390' }
}

/** 工具名 → 中文可读名（界面只出现有出处的名称） */
export const TOOL_LABEL: Record<string, string> = {
  internet_search: '联网检索',
  query_database: '查询数据库',
  generate_markdown: '生成 Markdown',
  convert_md_to_pdf: '转换为 PDF',
  read_file_content: '读取文件',
  task: '调度子智能体',
}

export function toolLabel(raw: string): string {
  return TOOL_LABEL[raw] || raw
}
