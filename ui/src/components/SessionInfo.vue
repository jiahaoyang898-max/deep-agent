<script setup lang="ts">
/** 会话信息面板：只展示真实运行时数据，无占位/假统计 */
import { computed } from 'vue'
import { formatDuration } from '../types'

const props = defineProps<{
  threadId: string
  sessionPath: string
  connected: boolean
  stepCount: number
  fileCount: number
  startedAt: number | null
  finishedAt: number | null
  running: boolean
  now: number
}>()

const elapsed = computed(() => {
  const start = props.startedAt
  if (!start) return '—'
  const end = props.running ? props.now : props.finishedAt || start
  return formatDuration(Math.max(0, end - start))
})

const rows = computed(() => [
  { k: '线程 ID', v: props.threadId.slice(0, 8), mono: true, title: props.threadId, tone: '' },
  {
    k: '实时连接',
    v: props.connected ? '已连接' : '重连中',
    mono: false,
    title: '',
    tone: props.connected ? 'grass' : 'rose',
  },
  { k: '执行步骤', v: String(props.stepCount), mono: true, title: '', tone: '' },
  { k: '本次用时', v: elapsed.value, mono: true, title: '', tone: '' },
  { k: '产出文件', v: String(props.fileCount), mono: true, title: '', tone: '' },
])

function copyPath() {
  navigator.clipboard?.writeText(props.sessionPath)
}
</script>

<template>
  <div class="session-panel">
    <div class="panel-head">会话信息</div>

    <div class="rows">
      <div v-for="r in rows" :key="r.k" class="row">
        <span class="k">{{ r.k }}</span>
        <span class="v" :class="[{ num: r.mono }, r.tone ? `tone-${r.tone}` : '']" :title="r.title">
          <i v-if="r.tone" class="dot"></i>{{ r.v }}
        </span>
      </div>
    </div>

    <div class="block">
      <div class="block-head">
        <span>工作目录</span>
        <button class="copy-btn" title="复制工作目录路径" @click="copyPath">复制</button>
      </div>
      <p class="path num" :title="sessionPath">{{ sessionPath || '任务开始后生成…' }}</p>
    </div>
  </div>
</template>

<style scoped>
.panel-head {
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.08em;
  color: var(--c-text-3);
  text-transform: uppercase;
  padding: 2px 2px 12px;
}
.rows {
  display: flex;
  flex-direction: column;
  gap: 1px;
  background: var(--c-line);
  border: 1px solid var(--c-line);
  border-radius: var(--r-md);
  overflow: hidden;
}
.row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 9px 12px;
  background: var(--c-surface);
}
.k {
  font-size: 12.5px;
  color: var(--c-text-3);
  white-space: nowrap;
}
.v {
  font-size: 13px;
  font-weight: 600;
  color: var(--c-text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.v .dot {
  display: inline-block;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  margin-right: 6px;
  vertical-align: 1px;
}
.tone-grass {
  color: var(--c-grass);
}
.tone-grass .dot {
  background: var(--c-grass);
}
.tone-rose {
  color: var(--c-rose);
}
.tone-rose .dot {
  background: var(--c-rose);
  animation: breathe 1.2s ease-in-out infinite;
}

.block {
  margin-top: 14px;
}
.block-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
  font-size: 12.5px;
  color: var(--c-text-3);
}
.copy-btn {
  font-size: 11px;
  color: var(--c-brand);
  padding: 2px 7px;
  border-radius: var(--r-xs);
  transition: background var(--dur-1);
}
.copy-btn:hover {
  background: var(--c-brand-soft);
}
.path {
  font-size: 11px;
  line-height: 1.65;
  color: var(--c-text-2);
  background: var(--c-surface-2);
  border: 1px solid var(--c-line);
  border-radius: var(--r-sm);
  padding: 8px 10px;
  word-break: break-all;
}
</style>
