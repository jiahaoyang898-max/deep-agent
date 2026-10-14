/** 轻量全局 Toast */
import { reactive } from 'vue'

export interface ToastItem {
  id: number
  kind: 'success' | 'error' | 'info'
  text: string
}

export const toasts = reactive<ToastItem[]>([])
let seq = 0

export function toast(text: string, kind: ToastItem['kind'] = 'info', duration = 2600) {
  const id = ++seq
  toasts.push({ id, kind, text })
  setTimeout(() => {
    const i = toasts.findIndex((t) => t.id === id)
    if (i >= 0) toasts.splice(i, 1)
  }, duration)
}
