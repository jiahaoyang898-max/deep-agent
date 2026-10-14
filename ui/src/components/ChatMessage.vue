<script setup lang="ts">
import { computed, ref, onMounted } from 'vue'
import { marked } from 'marked'
import type { Message } from '../types'
import { fileMeta, formatDuration, toolLabel } from '../types'

marked.setOptions({ breaks: true, gfm: true })

const props = defineProps<{
  msg: Message
  running: boolean
  isLast: boolean
}>()

const logsOpen = ref(false)
const copied = ref(false)

const isUser = computed(() => props.msg.role === 'user')
const isAi = computed(() => props.msg.role === 'ai')

const rendered = computed(() =>
  props.msg.content ? (marked.parse(props.msg.content, { async: false }) as string) : '',
)

/** 最后一条 AI 且任务在跑：显示"工作中" */
const working = computed(() => isAi.value && props.running && props.isLast)

interface Step {
  icon: string
  title: string
  detail: any
  elapsed: string
  state: 'done' | 'running'
}

/** 结构化的步骤（含每步耗时，数字等宽对齐） */
const steps = computed<Step[]>(() => {
  const logs = props.msg.logs || []
  const now = Date.now()
  return logs.map((log, i) => {
    const next = logs[i + 1]
    const end = next?.ts ?? (props.running && props.isLast ? now : props.msg.finishedAt ?? undefined)
    const elapsed = log.ts && end ? formatDuration(Math.max(0, end - log.ts)) : '—'
    const isRunning = props.running && props.isLast && i === logs.length - 1 && !props.msg.content
    return {
      icon: stepIcon(log.title),
      title: stepTitle(log.title),
      detail: log.details,
      elapsed,
      state: isRunning ? 'running' : 'done',
    }
  })
})

/** 本条消息总耗时 */
const totalElapsed = computed(() => {
  if (!props.msg.timestamp || !props.msg.finishedAt) return ''
  return formatDuration(props.msg.finishedAt - props.msg.timestamp)
})

function stepTitle(title: string): string {
  if (title.startsWith('正在使用助手')) return title.replace('正在使用助手：', '调度子智能体 · ')
  if (title.startsWith('上传')) return title
  const m = title.match(/使用的工具：\s*(\w+)/)
  if (!m || !m[1]) return title
  return toolLabel(m[1])
}

function stepIcon(title: string): string {
  if (title.startsWith('正在使用助手')) return '🤖'
  if (title.startsWith('上传')) return '📎'
  const m = title.match(/使用的工具：\s*(\w+)/)
  const name = m?.[1] || ''
  const map: Record<string, string> = {
    internet_search: '🌐',
    query_database: '🗄️',
    generate_markdown: '📝',
    convert_md_to_pdf: '📕',
    read_file_content: '📖',
  }
  return map[name] || '🔧'
}

const timeLabel = computed(() => {
  if (!props.msg.timestamp) return ''
  const d = new Date(props.msg.timestamp)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
})

/** 给代码块挂复制按钮（纯增强） */
function decorateCode(html: string): string {
  return html
    .replace(/<pre>/g, '<div class="code-wrap"><button class="code-copy" type="button">复制</button><pre>')
    .replace(/<\/pre>/g, '</pre></div>')
}

const bodyHtml = computed(() => (rendered.value ? decorateCode(rendered.value) : ''))
const bodyRef = ref<HTMLElement | null>(null)

async function copyAll() {
  try {
    await navigator.clipboard.writeText(props.msg.content)
    copied.value = true
    setTimeout(() => (copied.value = false), 1600)
  } catch {
    /* 剪贴板不可用时静默 */
  }
}

onMounted(() => {
  bodyRef.value?.addEventListener('click', (e) => {
    const btn = (e.target as HTMLElement).closest('.code-copy') as HTMLElement | null
    if (!btn) return
    const code = btn.parentElement?.querySelector('code')?.textContent || ''
    navigator.clipboard?.writeText(code)
    btn.textContent = '已复制'
    btn.classList.add('copied')
    setTimeout(() => {
      btn.textContent = '复制'
      btn.classList.remove('copied')
    }, 1500)
  })
})
</script>

<template>
  <div class="row" :class="msg.role">
    <!-- 用户 -->
    <div v-if="isUser" class="user-wrap anim-up">
      <div class="bubble-user">{{ msg.content }}</div>
      <span class="meta num">{{ timeLabel }}</span>
    </div>

    <!-- 系统提示 -->
    <div v-else-if="msg.role === 'system'" class="sys anim-pop">
      <span aria-hidden="true">⚠</span>{{ msg.content }}
    </div>

    <!-- AI -->
    <div v-else class="ai anim-up">
      <div class="avatar" aria-hidden="true">
        <svg width="17" height="17" viewBox="0 0 24 24" fill="none">
          <path d="M12 2l2.6 7.4L22 12l-7.4 2.6L12 22l-2.6-7.4L2 12l7.4-2.6z" fill="#fff" />
        </svg>
      </div>

      <div class="ai-body">
        <!-- 头部：名称 + 状态 + 总耗时 -->
        <div class="ai-head">
          <span class="ai-name">深度调研智能体</span>
          <span v-if="working" class="chip chip-cyan"><i class="dot-breathe"></i>工作中</span>
          <span v-else-if="totalElapsed" class="chip chip-amber">
            耗时 <b class="num">{{ totalElapsed }}</b>
          </span>
          <span class="meta num">{{ timeLabel }}</span>
        </div>

        <!-- 执行步骤时间线 -->
        <div v-if="steps.length" class="steps-card glass glowline">
          <button class="steps-head" :aria-expanded="logsOpen" @click="logsOpen = !logsOpen">
            <span class="state" :class="working ? 'run' : 'ok'">
              <i v-if="working" class="spin"></i>
              <template v-else>✓</template>
            </span>
            <span class="steps-title">
              {{ working ? '正在检索与推理…' : `已完成 ${steps.length} 个步骤` }}
            </span>
            <span class="chev" :class="{ open: logsOpen }" aria-hidden="true">⌄</span>
          </button>

          <transition name="fold">
            <ol v-if="logsOpen" class="steps">
              <li v-for="(s, i) in steps" :key="i" class="step" :class="s.state">
                <span class="node" aria-hidden="true"><i></i></span>
                <div class="step-main">
                  <div class="step-line">
                    <span class="step-ico" aria-hidden="true">{{ s.icon }}</span>
                    <span class="step-name">{{ s.title }}</span>
                    <span class="step-elapsed num">{{ s.elapsed }}</span>
                  </div>
                  <details v-if="s.detail" class="step-detail">
                    <summary>查看参数</summary>
                    <pre class="num">{{
                      typeof s.detail === 'string' ? s.detail : JSON.stringify(s.detail, null, 2)
                    }}</pre>
                  </details>
                </div>
              </li>
            </ol>
          </transition>
        </div>

        <!-- 正文 -->
        <div v-if="msg.content" ref="bodyRef" class="bubble-ai md-body" v-html="bodyHtml"></div>
        <div v-else-if="working" class="typing" role="status" aria-label="正在生成回答">
          <i></i><i></i><i></i>
        </div>

        <!-- 产出文件 -->
        <div v-if="msg.files && msg.files.length" class="files">
          <a
            v-for="f in msg.files"
            :key="f.path"
            class="file-card glowline"
            :href="f.url"
            target="_blank"
            rel="noopener"
            :title="`下载 ${f.name}`"
          >
            <span class="stripe" :style="{ background: fileMeta(f.name).tone }"></span>
            <span class="f-ico" aria-hidden="true">{{ fileMeta(f.name).icon }}</span>
            <span class="f-name">{{ f.name }}</span>
            <span class="f-kind chip">{{ fileMeta(f.name).kind }}</span>
            <span class="f-dl" aria-hidden="true">↓</span>
          </a>
        </div>

        <!-- 操作条（只保留真实动作） -->
        <div v-if="msg.content" class="actions">
          <button class="act" type="button" title="复制全文" @click="copyAll">
            {{ copied ? '✓ 已复制' : '⧉ 复制全文' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.row {
  display: flex;
  margin-bottom: 22px;
}
.row.user {
  justify-content: flex-end;
}

/* ---------- 用户气泡 ---------- */
.user-wrap {
  max-width: 74%;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
}
.bubble-user {
  padding: 12px 17px;
  background: var(--c-grad);
  color: #fff;
  border-radius: 18px 18px 6px 18px;
  box-shadow: 0 6px 20px rgba(85, 99, 255, 0.26);
  font-size: 14.5px;
  line-height: 1.72;
  white-space: pre-wrap;
  word-break: break-word;
}
.meta {
  font-size: 11px;
  color: var(--c-text-3);
  margin-top: 5px;
}

/* ---------- 系统提示 ---------- */
.sys {
  margin: 0 auto;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 16px;
  background: var(--c-rose-soft);
  border: 1px solid #f3cdcb;
  color: var(--c-rose);
  border-radius: var(--r-full);
  font-size: 13px;
  max-width: 82%;
}

/* ---------- AI ---------- */
.ai {
  display: flex;
  gap: 12px;
  max-width: 88%;
}
.avatar {
  flex: 0 0 auto;
  width: 32px;
  height: 32px;
  border-radius: 10px;
  background: var(--c-grad);
  display: grid;
  place-items: center;
  box-shadow: var(--sh-brand);
  margin-top: 3px;
}
.ai-body {
  flex: 1;
  min-width: 0;
}
.ai-head {
  display: flex;
  align-items: center;
  gap: 9px;
  margin-bottom: 9px;
  min-height: 20px;
  white-space: nowrap;
}
.ai-name {
  font-size: 13px;
  font-weight: 700;
  color: var(--c-ink);
}
.ai-head .meta {
  margin-top: 0;
}
.chip .dot-breathe {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--c-cyan);
  animation: breathe 1.1s ease-in-out infinite;
}

/* 步骤卡 */
.steps-card {
  border-radius: var(--r-md);
  overflow: hidden;
  margin-bottom: 10px;
  background: var(--c-surface);
}
.steps-head {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 10px 14px;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--c-text-2);
  text-align: left;
}
.steps-head:hover {
  background: var(--c-surface-2);
}
.state {
  display: grid;
  place-items: center;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  font-size: 11px;
  flex: 0 0 auto;
}
.state.ok {
  background: var(--c-grass-soft);
  color: var(--c-grass);
}
.state.run {
  background: var(--c-cyan-soft);
}
.spin {
  width: 11px;
  height: 11px;
  border: 2px solid rgba(8, 145, 178, 0.25);
  border-top-color: var(--c-cyan);
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
}
.steps-title {
  flex: 1;
}
.chev {
  color: var(--c-text-3);
  transition: transform var(--dur-2) var(--ease-out);
}
.chev.open {
  transform: rotate(180deg);
}

.steps {
  list-style: none;
  padding: 4px 14px 12px 14px;
}
.step {
  display: flex;
  gap: 12px;
  animation: fadeUp var(--dur-3) var(--ease-out) both;
}
.node {
  position: relative;
  display: flex;
  justify-content: center;
  width: 10px;
  flex: 0 0 auto;
  padding-top: 8px;
}
.node::before {
  content: "";
  position: absolute;
  top: 14px;
  bottom: -6px;
  width: 1px;
  background: var(--c-line);
}
.step:last-child .node::before {
  display: none;
}
.node i {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--c-grass);
  box-shadow: 0 0 0 3px var(--c-grass-soft);
  z-index: 1;
}
.step.running .node i {
  background: var(--c-cyan);
  box-shadow: 0 0 0 3px var(--c-cyan-soft);
  animation: breathe 1.1s ease-in-out infinite;
}
.step-main {
  flex: 1;
  min-width: 0;
  padding: 4px 0 10px;
}
.step-line {
  display: flex;
  align-items: center;
  gap: 8px;
  white-space: nowrap;
}
.step-ico {
  font-size: 13px;
}
.step-name {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--c-text-2);
  overflow: hidden;
  text-overflow: ellipsis;
}
.step-elapsed {
  margin-left: auto;
  font-size: 11px;
  color: var(--c-amber);
  background: var(--c-amber-soft);
  border-radius: var(--r-xs);
  padding: 1px 6px;
  white-space: nowrap;
}
.step-detail {
  margin-top: 4px;
}
.step-detail summary {
  font-size: 11.5px;
  color: var(--c-text-3);
  cursor: pointer;
  width: fit-content;
}
.step-detail summary:hover {
  color: var(--c-brand);
}
.step-detail pre {
  margin-top: 5px;
  padding: 9px 11px;
  background: var(--c-code-bg);
  border: 1px solid var(--c-line);
  border-radius: var(--r-sm);
  font-size: 11.5px;
  line-height: 1.6;
  color: var(--c-text-2);
  overflow-x: auto;
  max-height: 180px;
}
.fold-enter-from,
.fold-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}
.fold-enter-active,
.fold-leave-active {
  transition: opacity var(--dur-2) var(--ease-out), transform var(--dur-2) var(--ease-out);
}

/* 正文气泡：层次来自描边 + 极浅阴影 */
.bubble-ai {
  padding: 14px 18px;
  background: var(--c-surface);
  border: 1px solid var(--c-line);
  border-radius: 6px 18px 18px 18px;
  box-shadow: var(--sh-1);
}
.typing {
  display: inline-flex;
  gap: 5px;
  padding: 14px 18px;
  background: var(--c-surface);
  border: 1px solid var(--c-line);
  border-radius: 6px 18px 18px 18px;
  box-shadow: var(--sh-1);
}
.typing i {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--c-brand);
  animation: bounceDot 1.2s infinite;
}
.typing i:nth-child(2) {
  animation-delay: 0.15s;
}
.typing i:nth-child(3) {
  animation-delay: 0.3s;
}

/* 产出文件卡片 */
.files {
  display: flex;
  flex-wrap: wrap;
  gap: 9px;
  margin-top: 11px;
}
.file-card {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 9px;
  padding: 9px 13px 9px 15px;
  background: var(--c-surface);
  border: 1px solid var(--c-line);
  border-radius: var(--r-md);
  box-shadow: var(--sh-1);
  overflow: hidden;
  transition: transform var(--dur-2) var(--ease-out), box-shadow var(--dur-2);
}
.file-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--sh-3);
}
.stripe {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
}
.f-ico {
  font-size: 16px;
}
.f-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--c-text);
  max-width: 260px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.f-dl {
  color: var(--c-brand);
  font-size: 14px;
  opacity: 0;
  transition: opacity var(--dur-1);
}
.file-card:hover .f-dl,
.file-card:focus-visible .f-dl {
  opacity: 1;
}

/* 操作条：hover 浮现，键盘聚焦也可见 */
.actions {
  display: flex;
  gap: 8px;
  margin-top: 7px;
  min-height: 22px;
}
.act {
  font-size: 11.5px;
  font-weight: 600;
  color: var(--c-text-3);
  padding: 3px 9px;
  border-radius: var(--r-xs);
  opacity: 0;
  transition: opacity var(--dur-1), background var(--dur-1), color var(--dur-1);
}
.ai:hover .act,
.act:focus-visible {
  opacity: 1;
}
.act:hover {
  background: var(--c-brand-soft);
  color: var(--c-brand);
}
</style>
