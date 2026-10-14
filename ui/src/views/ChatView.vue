<script setup lang="ts">
/**
 * 工作台主界面
 * 保留原 App.vue 全部功能：WebSocket 事件流、文件上传/列表/下载、
 * Markdown 渲染、思考过程外显；后端契约零改动。
 * v2 新增：⌘K 命令面板、右侧双 Tab 面板、逐步耗时、快捷键、焦点态与响应式断点。
 */
import { ref, onMounted, onBeforeUnmount, nextTick, computed, watch } from 'vue'
import ChatMessage from '../components/ChatMessage.vue'
import FilePanel from '../components/FilePanel.vue'
import SessionInfo from '../components/SessionInfo.vue'
import CommandPalette, { type Command } from '../components/CommandPalette.vue'
import { api, authApi } from '../api'
import type { FileMeta } from '../api'
import type { Message } from '../types'
import { relativeTime } from '../types'
import { toast } from '../toasts'

const props = defineProps<{ username: string }>()
const emit = defineEmits<{ (e: 'logout'): void }>()

/* ================= 状态 ================= */
const inputQuery = ref('')
const messages = ref<Message[]>([])
const status = ref<'idle' | 'running'>('idle')
const socket = ref<WebSocket | null>(null)
const wsConnected = ref(false)
const currentSessionPath = ref('')
const fileList = ref<FileMeta[]>([])
const filesLoading = ref(false)
const isSidebarOpen = ref(false)
const rightTab = ref<'files' | 'session'>('files')
const userMenuOpen = ref(false)
const paletteOpen = ref(false)
const currentThreadId = ref<string>(crypto.randomUUID())
const taskStartedAt = ref<number | null>(null)
const taskFinishedAt = ref<number | null>(null)
const now = ref(Date.now())
let ticker: number | undefined

const isWelcome = computed(() => messages.value.length === 0)

/** 最后一条 AI 消息的步骤数（真实数据） */
const stepCount = computed(() => {
  const lastAi = [...messages.value].reverse().find((m) => m.role === 'ai')
  return lastAi?.logs?.length || 0
})

/* 文件选择 */
const fileInputRef = ref<HTMLInputElement | null>(null)
const composerRef = ref<HTMLTextAreaElement | null>(null)
const selectedFiles = ref<File[]>([])
const isDragging = ref(false)

/* ================= 会话历史 ================= */
interface SessionItem {
  threadId: string
  title: string
  savedAt: number
  messages: Message[]
  sessionPath: string
}
const SESSIONS_KEY = 'das_sessions'
const sessions = ref<SessionItem[]>(loadSessions())

function loadSessions(): SessionItem[] {
  try {
    return JSON.parse(localStorage.getItem(SESSIONS_KEY) || '[]')
  } catch {
    return []
  }
}
function persistSessions() {
  localStorage.setItem(SESSIONS_KEY, JSON.stringify(sessions.value.slice(0, 40)))
}
function saveCurrentSession() {
  if (!messages.value.length) return
  const firstUser = messages.value.find((m) => m.role === 'user')
  const item: SessionItem = {
    threadId: currentThreadId.value,
    title: (firstUser?.content || '新会话').slice(0, 42),
    savedAt: Date.now(),
    messages: JSON.parse(JSON.stringify(messages.value)),
    sessionPath: currentSessionPath.value,
  }
  const idx = sessions.value.findIndex((s) => s.threadId === currentThreadId.value)
  if (idx >= 0) sessions.value[idx] = item
  else sessions.value.unshift(item)
  persistSessions()
}

/** 历史会话按「今天 / 更早」分组 */
const groupedSessions = computed(() => {
  const today: SessionItem[] = []
  const earlier: SessionItem[] = []
  const todayStr = new Date().toDateString()
  sessions.value.forEach((s) => {
    if (new Date(s.savedAt).toDateString() === todayStr) today.push(s)
    else earlier.push(s)
  })
  return [
    { label: '今天', items: today },
    { label: '更早', items: earlier },
  ].filter((g) => g.items.length)
})

/* ================= 滚动 ================= */
const messagesEndRef = ref<HTMLElement | null>(null)
async function scrollToBottom(smooth = true) {
  await nextTick()
  messagesEndRef.value?.scrollIntoView({ behavior: smooth ? 'smooth' : 'auto' })
}

/* ================= WebSocket ================= */
function connectWebSocket() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  const ws = new WebSocket(`${proto}://${location.host}/ws/${currentThreadId.value}`)
  ws.onopen = () => (wsConnected.value = true)
  ws.onmessage = (e) => {
    try {
      handleSocketMessage(JSON.parse(e.data))
    } catch (err) {
      console.error('WS 消息解析失败:', err)
    }
  }
  ws.onclose = () => {
    wsConnected.value = false
    setTimeout(connectWebSocket, 3000)
  }
  ws.onerror = () => (wsConnected.value = false)
  socket.value = ws
}

function handleSocketMessage(data: any) {
  const { type, event, message, data: eventData } = data
  if (type === 'pong') return

  const lastAiMsg = messages.value.slice().reverse().find((m) => m.role === 'ai')

  if (event === 'session_created') {
    currentSessionPath.value = eventData.path
    isSidebarOpen.value = true
    fetchFiles()
  } else if (event === 'tool_start') {
    if (currentSessionPath.value) {
      fetchFiles()
      setTimeout(fetchFiles, 2000)
    }
    if (lastAiMsg) {
      if (!lastAiMsg.logs) lastAiMsg.logs = []
      lastAiMsg.logs.push({
        type: 'tool',
        title: `使用的工具： ${eventData.tool_name}...`,
        details: eventData.args,
        timestamp: new Date().toLocaleTimeString(),
        ts: Date.now(),
      })
      if (eventData.args?.filename && currentSessionPath.value) {
        if (!lastAiMsg.files) lastAiMsg.files = []
        const abs = `${currentSessionPath.value}/${eventData.args.filename}`
        if (!lastAiMsg.files.find((f) => f.name === eventData.args.filename)) {
          lastAiMsg.files.push({
            name: eventData.args.filename,
            path: abs,
            url: api.downloadUrl(abs),
          })
        }
      }
    }
  } else if (event === 'assistant_call') {
    if (currentSessionPath.value) fetchFiles()
    if (lastAiMsg) {
      if (!lastAiMsg.logs) lastAiMsg.logs = []
      lastAiMsg.logs.push({
        type: 'agent',
        title: `正在使用助手： ${eventData.assistant_name}...`,
        details: eventData.args,
        timestamp: new Date().toLocaleTimeString(),
        ts: Date.now(),
      })
    }
  } else if (event === 'task_result') {
    if (lastAiMsg) {
      lastAiMsg.content = eventData.result
      lastAiMsg.finishedAt = Date.now()
    } else {
      messages.value.push({
        role: 'ai',
        content: eventData.result,
        timestamp: Date.now(),
        finishedAt: Date.now(),
      })
    }
    status.value = 'idle'
    taskFinishedAt.value = Date.now()
    fetchFiles()
    saveCurrentSession()
  } else if (event === 'error') {
    messages.value.push({
      role: 'system',
      content: message || '智能体执行出错',
      timestamp: Date.now(),
    })
    status.value = 'idle'
    taskFinishedAt.value = Date.now()
    saveCurrentSession()
  }

  scrollToBottom()
}

/* ================= 文件 ================= */
async function fetchFiles() {
  if (!currentSessionPath.value) return
  filesLoading.value = fileList.value.length === 0
  try {
    const res = await api.listFiles(currentSessionPath.value)
    fileList.value = res.data.files || []
  } catch (e) {
    console.error('获取文件列表失败:', e)
  } finally {
    filesLoading.value = false
  }
}

/* ================= 发送 ================= */
async function sendMessage() {
  if ((!inputQuery.value.trim() && !selectedFiles.value.length) || status.value === 'running') return

  const query = inputQuery.value
  inputQuery.value = ''
  autoResize()
  status.value = 'running'
  taskStartedAt.value = Date.now()
  taskFinishedAt.value = null

  messages.value.push({ role: 'user', content: query, timestamp: Date.now() })
  const aiMsg: Message = { role: 'ai', content: '', logs: [], files: [], timestamp: Date.now() }
  messages.value.push(aiMsg)
  scrollToBottom()

  if (selectedFiles.value.length) {
    if (!aiMsg.logs) aiMsg.logs = []
    aiMsg.logs.push({
      type: 'info',
      title: `上传 ${selectedFiles.value.length} 个文件…`,
      details: selectedFiles.value.map((f) => ({ name: f.name, size: f.size })),
      timestamp: new Date().toLocaleTimeString(),
      ts: Date.now(),
    })
    try {
      await api.uploadFiles(selectedFiles.value, currentThreadId.value)
      selectedFiles.value = []
      aiMsg.logs.push({
        type: 'success',
        title: '文件上传成功',
        details: null,
        timestamp: new Date().toLocaleTimeString(),
        ts: Date.now(),
      })
    } catch (e: any) {
      aiMsg.logs.push({
        type: 'error',
        title: '文件上传失败',
        details: e.message || '未知错误',
        timestamp: new Date().toLocaleTimeString(),
        ts: Date.now(),
      })
      toast('文件上传失败，任务仍会继续执行', 'error')
    }
  }

  try {
    await api.startTask(query, currentThreadId.value)
  } catch (error: any) {
    let msg = '任务启动失败'
    if (error.message) msg += `（${error.message}）`
    if (error.response?.data) msg += ` 服务端返回：${JSON.stringify(error.response.data)}`
    messages.value.push({ role: 'system', content: msg, timestamp: Date.now() })
    status.value = 'idle'
    taskFinishedAt.value = Date.now()
  }
  scrollToBottom()
}

/* ================= 会话操作 ================= */
function newChat() {
  if (status.value === 'running') {
    toast('当前任务仍在执行，稍候再开新会话', 'info')
    return
  }
  saveCurrentSession()
  socket.value?.close()
  currentThreadId.value = crypto.randomUUID()
  messages.value = []
  currentSessionPath.value = ''
  fileList.value = []
  taskStartedAt.value = null
  taskFinishedAt.value = null
  connectWebSocket()
  toast('已开启新会话', 'success')
}

function restoreSession(s: SessionItem) {
  if (status.value === 'running') {
    toast('当前任务仍在执行，稍候再切换会话', 'info')
    return
  }
  if (s.threadId === currentThreadId.value) return
  saveCurrentSession()
  socket.value?.close()
  currentThreadId.value = s.threadId
  messages.value = JSON.parse(JSON.stringify(s.messages))
  currentSessionPath.value = s.sessionPath
  const lastAi = [...messages.value].reverse().find((m) => m.role === 'ai')
  taskStartedAt.value = messages.value[0]?.timestamp || null
  taskFinishedAt.value = lastAi?.finishedAt || null
  fileList.value = []
  if (currentSessionPath.value) {
    isSidebarOpen.value = true
    fetchFiles()
  }
  connectWebSocket()
  scrollToBottom(false)
}

function removeSession(id: string, e: Event) {
  e.stopPropagation()
  sessions.value = sessions.value.filter((s) => s.threadId !== id)
  persistSessions()
}

/* ================= 登出 ================= */
async function handleLogout() {
  userMenuOpen.value = false
  try {
    await authApi.logout()
  } catch {
    /* 本地退出即可 */
  }
  socket.value?.close()
  toast('已退出登录', 'success')
  emit('logout')
}

/* ================= 拖拽上传 ================= */
function onDragOver(e: DragEvent) {
  e.preventDefault()
  if (e.dataTransfer?.types.includes('Files')) isDragging.value = true
}
function onDragLeave(e: DragEvent) {
  e.preventDefault()
  if (e.currentTarget === e.target) isDragging.value = false
}
function onDrop(e: DragEvent) {
  e.preventDefault()
  isDragging.value = false
  const files = Array.from(e.dataTransfer?.files || [])
  if (files.length) addFiles(files)
}
function addFiles(files: File[]) {
  selectedFiles.value = [...selectedFiles.value, ...files]
}
function triggerFileUpload() {
  fileInputRef.value?.click()
}
function handleFileChange(event: Event) {
  const target = event.target as HTMLInputElement
  if (target.files?.length) {
    addFiles(Array.from(target.files))
    target.value = ''
  }
}
function removeFile(index: number) {
  selectedFiles.value.splice(index, 1)
}

/* ================= 输入框 ================= */
function autoResize() {
  const el = composerRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 176)}px`
}
function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
    e.preventDefault()
    sendMessage()
  }
}

const isMac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent)
/** 修饰键按平台显示：macOS 用 ⌘，其余用 Ctrl（与真实绑定一致） */
const mod = isMac ? '⌘' : 'Ctrl'

/* ================= 命令面板 ================= */
const commands = computed<Command[]>(() => {
  const list: Command[] = [
    { id: 'new', label: '开启新会话', group: '会话', keyHint: `${mod} ⏎`, run: newChat },
    {
      id: 'files',
      label: isSidebarOpen.value ? '收起右侧面板' : '展开右侧面板',
      hint: '产物文件 / 会话信息',
      group: '视图',
      keyHint: `${mod} B`,
      run: () => (isSidebarOpen.value = !isSidebarOpen.value),
    },
    {
      id: 'copy-path',
      label: '复制当前会话工作目录',
      hint: currentSessionPath.value || '暂无目录',
      group: '视图',
      run: () => {
        if (!currentSessionPath.value) return toast('当前会话还没有工作目录', 'info')
        navigator.clipboard?.writeText(currentSessionPath.value)
        toast('工作目录已复制', 'success')
      },
    },
    { id: 'logout', label: '退出登录', group: '账号', run: handleLogout },
  ]
  sessions.value.slice(0, 8).forEach((s) => {
    list.push({
      id: `s-${s.threadId}`,
      label: `切换到：${s.title}`,
      hint: relativeTime(s.savedAt),
      group: '历史会话',
      run: () => restoreSession(s),
    })
  })
  return list
})

/* ================= 建议（贴合医药调研场景） ================= */
const suggestions = [
  { ico: '🗄️', text: '查询库存最少的 10 种药品，生成库存预警清单', tag: '数据库' },
  { ico: '🌐', text: '联网检索沃华医药最新动态，输出调研简报', tag: '联网检索' },
  { ico: '📄', text: '分析主力产品销售数据，生成 PDF 分析报告', tag: '报告产出' },
  { ico: '🧪', text: '结合数据库与网络资讯，评估心可舒片市场竞争力', tag: '综合' },
]
function useSuggestion(text: string) {
  inputQuery.value = text
  composerRef.value?.focus()
  autoResize()
}

/** 能力胶囊：全部对应真实已挂载工具 */
const capabilities = ['联网检索', 'MySQL 业务库', 'RAG 知识库', 'Markdown 成稿', 'PDF 导出']

/* ================= 全局快捷键 ================= */
function onGlobalKeydown(e: KeyboardEvent) {
  const meta = e.metaKey || e.ctrlKey
  if (meta && e.key.toLowerCase() === 'k') {
    e.preventDefault()
    paletteOpen.value = !paletteOpen.value
  } else if (meta && e.key.toLowerCase() === 'b') {
    e.preventDefault()
    if (currentSessionPath.value) isSidebarOpen.value = !isSidebarOpen.value
  } else if (meta && e.key === 'Enter') {
    e.preventDefault()
    newChat()
  }
}
function onDocClick(e: MouseEvent) {
  if (!(e.target as HTMLElement).closest('.user-menu-wrap')) userMenuOpen.value = false
}

onMounted(() => {
  connectWebSocket()
  document.addEventListener('click', onDocClick)
  window.addEventListener('keydown', onGlobalKeydown)
  ticker = window.setInterval(() => (now.value = Date.now()), 1000)
})
onBeforeUnmount(() => {
  document.removeEventListener('click', onDocClick)
  window.removeEventListener('keydown', onGlobalKeydown)
  if (ticker) clearInterval(ticker)
  socket.value?.close()
})

watch(status, (v) => {
  if (v === 'running') scrollToBottom()
})
</script>

<template>
  <div class="page" @dragover="onDragOver" @dragleave="onDragLeave" @drop="onDrop">
    <div class="ambient" aria-hidden="true">
      <span class="orb" style="width: 380px; height: 380px; left: -110px; top: -90px; background: radial-gradient(circle, rgba(85, 99, 255, 0.24), transparent 70%)"></span>
      <span class="orb" style="width: 320px; height: 320px; right: -90px; bottom: -110px; background: radial-gradient(circle, rgba(168, 85, 247, 0.19), transparent 70%); animation-delay: -6s"></span>
    </div>

    <!-- ===== 顶栏 ===== -->
    <header class="topbar glass">
      <div class="left">
        <div class="logo" aria-hidden="true">✦</div>
        <div class="brand">
          <b>Deep Agent Search</b>
          <small>深度调研智能体</small>
        </div>

        <button class="search-btn" type="button" :title="`打开命令面板（${mod} + K）`" @click="paletteOpen = true">
          <span aria-hidden="true">{{ isMac ? '⌘' : '⌃' }}</span>
          <span class="search-label">搜索动作</span>
          <span class="kbd">K</span>
        </button>
      </div>

      <div class="right">
        <span class="conn chip" :class="wsConnected ? 'chip-grass' : 'chip-amber'" :title="wsConnected ? '实时通道已连接' : '实时通道重连中'">
          <i class="conn-dot" :class="{ on: wsConnected }"></i>
          {{ wsConnected ? '实时通道正常' : '重连中' }}
        </span>

        <button class="btn btn-ghost new-btn" type="button" :title="`开启新会话（${mod} + Enter）`" @click="newChat">
          ＋ 新会话
        </button>

        <div class="user-menu-wrap">
          <button class="user-chip" type="button" :aria-expanded="userMenuOpen" title="账号菜单" @click.stop="userMenuOpen = !userMenuOpen">
            <span class="avatar">{{ username.charAt(0).toUpperCase() }}</span>
            <span class="uname">{{ username }}</span>
            <span class="caret" aria-hidden="true">⌄</span>
          </button>
          <transition name="menu">
            <div v-if="userMenuOpen" class="user-menu glass" role="menu">
              <div class="menu-head">
                <span class="avatar big">{{ username.charAt(0).toUpperCase() }}</span>
                <div>
                  <b>{{ username }}</b>
                  <small>已登录 · 会话本地留存</small>
                </div>
              </div>
              <button class="menu-item danger" type="button" role="menuitem" title="退出登录" @click="handleLogout">
                <span aria-hidden="true">⏻</span> 退出登录
              </button>
            </div>
          </transition>
        </div>
      </div>
    </header>

    <!-- ===== 主体 ===== -->
    <div class="body">
      <!-- 左：历史会话 -->
      <aside class="side left-side" aria-label="历史会话">
        <div class="side-head">
          <span>历史会话</span>
          <span class="num side-count">{{ sessions.length }}</span>
        </div>
        <div class="side-scroll">
          <button class="side-new" type="button" :title="`开启新会话（${mod} + Enter）`" @click="newChat">
            <span aria-hidden="true">＋</span> 新建会话
          </button>
          <div v-if="!sessions.length" class="side-empty">
            <span aria-hidden="true">💬</span>
            <p>还没有历史会话</p>
            <small>完成一次任务后会自动留存</small>
          </div>
          <template v-for="g in groupedSessions" :key="g.label">
            <div class="group-label">{{ g.label }}</div>
            <button
              v-for="s in g.items"
              :key="s.threadId"
              class="hist-item"
              type="button"
              :class="{ active: s.threadId === currentThreadId }"
              :title="s.title"
              @click="restoreSession(s)"
            >
              <span class="h-ico" aria-hidden="true">💬</span>
              <span class="h-main">
                <span class="h-title">{{ s.title }}</span>
                <span class="h-time num">{{ relativeTime(s.savedAt) }}</span>
              </span>
              <span
                class="h-del"
                role="button"
                tabindex="0"
                title="删除这条历史记录"
                @click="removeSession(s.threadId, $event)"
                @keydown.enter="removeSession(s.threadId, $event)"
                >✕</span
              >
            </button>
          </template>
        </div>
      </aside>

      <!-- 中：对话 -->
      <main class="main">
        <!-- 欢迎屏 -->
        <section v-if="isWelcome" class="welcome">
          <div class="hero-mark anim-pop" aria-hidden="true">✦</div>
          <h1 class="hero-title">你好，{{ username }}</h1>
          <p class="hero-sub">说一句话，我会联网检索、直查业务库、成稿并导出 PDF。</p>

          <p class="caps-label">已挂载能力</p>
          <div class="caps">
            <span v-for="c in capabilities" :key="c" class="chip chip-brand">{{ c }}</span>
          </div>

          <div class="sug-grid stagger">
            <button
              v-for="s in suggestions"
              :key="s.text"
              class="sug-card glowline"
              type="button"
              :title="s.text"
              @click="useSuggestion(s.text)"
            >
              <span class="sug-ico" aria-hidden="true">{{ s.ico }}</span>
              <span class="sug-body">
                <span class="sug-tag chip">{{ s.tag }}</span>
                <span class="sug-text">{{ s.text }}</span>
              </span>
              <span class="sug-arrow" aria-hidden="true">→</span>
            </button>
          </div>

          <p class="hero-tip">
            按 <span class="kbd">{{ mod }}</span><span class="kbd">K</span> 打开命令面板 · 支持把文件直接拖进对话区
          </p>
        </section>

        <!-- 消息流 -->
        <div v-else class="scroll">
          <div class="scroll-inner">
            <ChatMessage
              v-for="(msg, i) in messages"
              :key="i"
              :msg="msg"
              :running="status === 'running'"
              :is-last="i === messages.length - 1"
            />
            <div ref="messagesEndRef"></div>
          </div>
        </div>

        <!-- 输入区 -->
        <div class="composer-zone">
          <transition name="fold">
            <div v-if="selectedFiles.length" class="attach-strip">
              <div v-for="(f, i) in selectedFiles" :key="i" class="attach">
                <span aria-hidden="true">📎</span>
                <span class="attach-name">{{ f.name }}</span>
                <button class="attach-x" type="button" :title="`移除 ${f.name}`" @click="removeFile(i)">✕</button>
              </div>
            </div>
          </transition>

          <div class="composer glowline" :class="{ busy: status === 'running' }">
            <button class="icon-btn attach-btn" type="button" title="上传文件（也可直接拖入对话区）" @click="triggerFileUpload">
              📎
            </button>
            <textarea
              ref="composerRef"
              v-model="inputQuery"
              class="comp-input"
              rows="1"
              placeholder="描述你的调研需求…（Enter 发送，Shift+Enter 换行）"
              aria-label="调研需求输入框"
              @keydown="onKeydown"
              @input="autoResize"
            ></textarea>
            <button
              class="send-btn on-brand"
              type="button"
              :disabled="status === 'running' || (!inputQuery.trim() && !selectedFiles.length)"
              :title="status === 'running' ? '任务执行中' : '发送（Enter）'"
              @click="sendMessage"
            >
              <span v-if="status === 'running'" class="send-spin"></span>
              <span v-else aria-hidden="true">➤</span>
            </button>
          </div>

          <div class="comp-hint">
            <span>
              <span class="kbd">Enter</span> 发送 · <span class="kbd">⇧</span><span class="kbd">Enter</span> 换行 · 支持拖拽上传
            </span>
            <span class="state-txt" :class="status">
              <i aria-hidden="true"></i>{{ status === 'running' ? '智能体工作中' : '就绪' }}
            </span>
          </div>

          <input ref="fileInputRef" type="file" multiple hidden @change="handleFileChange" />
        </div>
      </main>

      <!-- 右：面板 -->
      <transition name="slide">
        <aside v-if="isSidebarOpen" class="side right-side" aria-label="面板">
          <div class="tabs" role="tablist" aria-label="面板切换">
            <button
              id="tab-files"
              class="tab"
              role="tab"
              type="button"
              :aria-selected="rightTab === 'files'"
              aria-controls="panel-files"
              :class="{ on: rightTab === 'files' }"
              @click="rightTab = 'files'"
            >
              产物文件
            </button>
            <button
              id="tab-session"
              class="tab"
              role="tab"
              type="button"
              :aria-selected="rightTab === 'session'"
              aria-controls="panel-session"
              :class="{ on: rightTab === 'session' }"
              @click="rightTab = 'session'"
            >
              会话信息
            </button>
            <button class="icon-btn close" type="button" :title="`收起面板（${mod} + B）`" @click="isSidebarOpen = false">
              »
            </button>
          </div>

          <div class="panel-body">
            <div v-show="rightTab === 'files'" id="panel-files" role="tabpanel" aria-labelledby="tab-files" class="pane">
              <FilePanel :files="fileList" :loading="filesLoading" />
            </div>
            <div v-show="rightTab === 'session'" id="panel-session" role="tabpanel" aria-labelledby="tab-session" class="pane">
              <SessionInfo
                :thread-id="currentThreadId"
                :session-path="currentSessionPath"
                :connected="wsConnected"
                :step-count="stepCount"
                :file-count="fileList.length"
                :started-at="taskStartedAt"
                :finished-at="taskFinishedAt"
                :running="status === 'running'"
                :now="now"
              />
            </div>
          </div>
        </aside>
      </transition>

      <button
        v-if="!isSidebarOpen && currentSessionPath"
        class="panel-open icon-btn"
        type="button"
        :title="`展开面板（${mod} + B）`"
        @click="isSidebarOpen = true"
      >
        «
      </button>
    </div>

    <CommandPalette :open="paletteOpen" :commands="commands" @close="paletteOpen = false" />

    <!-- 拖拽遮罩 -->
    <transition name="fade">
      <div v-if="isDragging" class="drop-mask">
        <div class="drop-box anim-pop">
          <span class="drop-ico" aria-hidden="true">📥</span>
          <p>松开即上传</p>
          <small>PDF / Word / Markdown / 图片 / 表格</small>
        </div>
      </div>
    </transition>
  </div>
</template>

<style scoped>
.page {
  position: relative;
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--c-bg);
  overflow: hidden;
}

/* ===== 顶栏 ===== */
.topbar {
  position: relative;
  z-index: 20;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 10px 18px;
  border: none;
  border-bottom: 1px solid var(--c-line);
  border-radius: 0;
}
.left {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}
.logo {
  width: 32px;
  height: 32px;
  border-radius: 10px;
  background: var(--c-grad);
  color: #fff;
  font-size: 15px;
  display: grid;
  place-items: center;
  box-shadow: var(--sh-brand);
  flex: 0 0 auto;
}
.brand {
  min-width: 0;
}
.brand b {
  display: block;
  font-size: 14px;
  font-weight: 700;
  color: var(--c-ink);
  line-height: 1.3;
  white-space: nowrap;
}
.brand small {
  display: block;
  font-size: 11px;
  color: var(--c-text-3);
  white-space: nowrap;
}

.search-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-left: 8px;
  padding: 7px 10px 7px 12px;
  border-radius: var(--r-md);
  border: 1px solid var(--c-line);
  background: var(--c-surface);
  color: var(--c-text-3);
  font-size: 12.5px;
  transition: border-color var(--dur-1), box-shadow var(--dur-1), color var(--dur-1);
}
.search-btn:hover {
  border-color: var(--c-brand-line);
  color: var(--c-text-2);
  box-shadow: var(--sh-2);
}
.search-label {
  min-width: 76px;
  text-align: left;
  white-space: nowrap;
}

.right {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 0 0 auto;
}
.conn {
  padding: 4px 10px;
}
.conn-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--c-amber);
  animation: breathe 1.2s ease-in-out infinite;
}
.conn-dot.on {
  background: var(--c-grass);
  animation: none;
}
.new-btn {
  padding: 7px 14px;
  font-size: 13px;
  border-radius: var(--r-md);
}

.user-menu-wrap {
  position: relative;
}
.user-chip {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 11px 4px 4px;
  border-radius: var(--r-full);
  border: 1px solid var(--c-line);
  background: var(--c-surface);
  transition: border-color var(--dur-1), box-shadow var(--dur-1);
}
.user-chip:hover {
  border-color: var(--c-line-strong);
  box-shadow: var(--sh-2);
}
.avatar {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  background: var(--c-grad);
  color: #fff;
  font-size: 12.5px;
  font-weight: 700;
  display: grid;
  place-items: center;
  flex: 0 0 auto;
}
.avatar.big {
  width: 36px;
  height: 36px;
  font-size: 15px;
}
.uname {
  font-size: 13px;
  font-weight: 600;
  max-width: 110px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.caret {
  font-size: 11px;
  color: var(--c-text-3);
}
.user-menu {
  position: absolute;
  right: 0;
  top: calc(100% + 8px);
  width: 226px;
  border-radius: var(--r-lg);
  box-shadow: var(--sh-3);
  overflow: hidden;
  z-index: 60;
}
.menu-head {
  display: flex;
  align-items: center;
  gap: 11px;
  padding: 13px 15px;
  border-bottom: 1px solid var(--c-line);
  background: var(--c-surface-2);
}
.menu-head b {
  display: block;
  font-size: 13.5px;
}
.menu-head small {
  font-size: 11.5px;
  color: var(--c-text-3);
}
.menu-item {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 11px 16px;
  font-size: 13px;
  font-weight: 600;
  color: var(--c-text-2);
  transition: background var(--dur-1), color var(--dur-1);
}
.menu-item:hover {
  background: var(--c-surface-2);
}
.menu-item.danger {
  color: var(--c-rose);
}
.menu-item.danger:hover {
  background: var(--c-rose-soft);
}
.menu-enter-from,
.menu-leave-to {
  opacity: 0;
  transform: translateY(-6px) scale(0.98);
}
.menu-enter-active,
.menu-leave-active {
  transition: opacity var(--dur-2) var(--ease-out), transform var(--dur-2) var(--ease-out);
}

/* ===== 三栏 ===== */
.body {
  position: relative;
  flex: 1;
  display: flex;
  min-height: 0;
}
.side {
  display: flex;
  flex-direction: column;
  flex: 0 0 auto;
}
.left-side {
  width: 244px;
  border-right: 1px solid var(--c-line);
  background: rgba(255, 255, 255, 0.5);
}
.side-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 15px 16px 9px;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.08em;
  color: var(--c-text-3);
  text-transform: uppercase;
  white-space: nowrap;
}
.side-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 20px;
  height: 20px;
  padding: 0 6px;
  border-radius: var(--r-full);
  background: var(--c-brand-soft);
  border: 1px solid var(--c-brand-line);
  color: var(--c-brand-deep);
  font-size: 11px;
  letter-spacing: 0;
}
.side-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 0 10px 16px;
}
.side-new {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 12px;
  margin-bottom: 6px;
  border-radius: var(--r-md);
  border: 1px dashed var(--c-line-strong);
  color: var(--c-text-2);
  font-size: 12.5px;
  font-weight: 650;
  transition: border-color var(--dur-1), color var(--dur-1), background var(--dur-1);
}
.side-new:hover {
  border-color: var(--c-brand);
  color: var(--c-brand-deep);
  background: var(--c-brand-soft);
}
.side-empty {
  text-align: center;
  padding: 42px 8px;
  color: var(--c-text-3);
}
.side-empty span {
  font-size: 26px;
  opacity: 0.7;
}
.side-empty p {
  margin-top: 8px;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--c-text-2);
}
.side-empty small {
  font-size: 11.5px;
}
.group-label {
  font-size: 11px;
  font-weight: 700;
  color: var(--c-text-3);
  padding: 10px 8px 5px;
  letter-spacing: 0.06em;
}
.hist-item {
  position: relative;
  width: 100%;
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 9px 10px;
  border-radius: var(--r-md);
  text-align: left;
  transition: background var(--dur-1);
}
.hist-item:hover {
  background: var(--c-bg-2);
}
.hist-item.active {
  background: var(--c-brand-soft);
}
.hist-item.active::before {
  content: "";
  position: absolute;
  left: 0;
  top: 9px;
  bottom: 9px;
  width: 2.5px;
  border-radius: 3px;
  background: var(--c-grad);
}
.h-ico {
  font-size: 13px;
  opacity: 0.8;
}
.h-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.h-title {
  font-size: 12.5px;
  color: var(--c-text-2);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.hist-item.active .h-title {
  color: var(--c-brand-deep);
  font-weight: 650;
}
.h-time {
  font-size: 10.5px;
  color: var(--c-text-3);
}
.h-del {
  opacity: 0;
  font-size: 11px;
  color: var(--c-text-3);
  padding: 3px 5px;
  border-radius: var(--r-xs);
  transition: opacity var(--dur-1), color var(--dur-1), background var(--dur-1);
}
.hist-item:hover .h-del,
.h-del:focus-visible {
  opacity: 1;
}
.h-del:hover {
  color: var(--c-rose);
  background: var(--c-rose-soft);
}

/* 中栏 */
.main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

/* 欢迎屏 */
.welcome {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 26px 30px;
  text-align: center;
  overflow-y: auto;
}
.hero-mark {
  width: 60px;
  height: 60px;
  border-radius: 20px;
  background: var(--c-grad);
  color: #fff;
  font-size: 26px;
  display: grid;
  place-items: center;
  box-shadow: var(--sh-brand);
  margin-bottom: 20px;
}
.hero-title {
  font-size: 30px;
  font-weight: 800;
  letter-spacing: -0.02em;
  color: var(--c-ink);
}
.hero-sub {
  margin-top: 6px;
  font-size: 14.5px;
  color: var(--c-text-2);
}
.caps-label {
  margin-top: 20px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.1em;
  color: var(--c-text-3);
  text-transform: uppercase;
}
.caps {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
  justify-content: center;
  margin-top: 9px;
}
.sug-grid {
  margin-top: 24px;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 11px;
  width: min(660px, 100%);
}
.sug-card {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  min-height: 88px;
  padding: 14px 16px;
  background: var(--c-surface);
  border: 1px solid var(--c-line);
  border-radius: var(--r-lg);
  box-shadow: var(--sh-1);
  text-align: left;
  transition: transform var(--dur-2) var(--ease-out), box-shadow var(--dur-2);
}
.sug-card:hover {
  transform: translateY(-3px);
  box-shadow: var(--sh-3);
}
.sug-ico {
  width: 36px;
  height: 36px;
  border-radius: var(--r-sm);
  display: grid;
  place-items: center;
  font-size: 17px;
  background: var(--c-brand-soft);
  border: 1px solid var(--c-brand-line);
  flex: 0 0 auto;
}
.sug-body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.sug-tag {
  align-self: flex-start;
  padding: 1px 7px;
}
.sug-text {
  font-size: 13px;
  font-weight: 550;
  color: var(--c-text-2);
  line-height: 1.55;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.sug-arrow {
  align-self: center;
  color: var(--c-text-3);
  opacity: 0;
  transform: translateX(-6px);
  transition: opacity var(--dur-2) var(--ease-out), transform var(--dur-2) var(--ease-out),
    color var(--dur-2);
}
.sug-card:hover .sug-arrow,
.sug-card:focus-visible .sug-arrow {
  opacity: 1;
  transform: none;
  color: var(--c-brand);
}
.hero-tip {
  margin-top: 20px;
  font-size: 11.5px;
  color: var(--c-text-3);
  display: flex;
  align-items: center;
  gap: 4px;
}

/* 消息流：底部渐隐，内容不会"撞"在输入框上 */
.scroll {
  flex: 1;
  overflow-y: auto;
  -webkit-mask-image: linear-gradient(to bottom, #000 calc(100% - 26px), transparent 100%);
  mask-image: linear-gradient(to bottom, #000 calc(100% - 26px), transparent 100%);
}
.scroll-inner {
  max-width: 880px;
  margin: 0 auto;
  padding: 26px 26px 8px;
}

/* 输入区 */
.composer-zone {
  width: 100%;
  max-width: 880px;
  margin: 0 auto;
  padding: 8px 26px 16px;
}
.attach-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
  margin-bottom: 8px;
}
.attach {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 5px 10px;
  border-radius: var(--r-full);
  background: var(--c-brand-soft);
  border: 1px solid var(--c-brand-line);
  color: var(--c-brand-deep);
  font-size: 11.5px;
  font-weight: 600;
  animation: popIn 0.24s var(--ease-spring) both;
}
.attach-name {
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.attach-x {
  font-size: 10px;
  opacity: 0.65;
  transition: opacity var(--dur-1);
}
.attach-x:hover {
  opacity: 1;
}

.composer {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  padding: 9px 11px;
  background: var(--c-surface);
  border: 1.5px solid var(--c-line);
  border-radius: 20px;
  box-shadow: var(--sh-2);
  transition: border-color var(--dur-2), box-shadow var(--dur-2);
}
.composer:focus-within {
  border-color: var(--c-brand);
  box-shadow: 0 0 0 4px rgba(85, 99, 255, 0.1), var(--sh-3);
}
.attach-btn {
  font-size: 16px;
}
.comp-input {
  flex: 1;
  border: none;
  resize: none;
  background: transparent;
  font-size: 14.5px;
  line-height: 1.65;
  max-height: 176px;
  padding: 7px 0;
  outline: none;
}
.comp-input::placeholder {
  color: var(--c-text-3);
}
.send-btn {
  width: 38px;
  height: 38px;
  border-radius: 13px;
  display: grid;
  place-items: center;
  font-size: 15px;
  color: #fff;
  background: var(--c-grad);
  background-size: 170% 170%;
  box-shadow: var(--sh-brand);
  flex: 0 0 auto;
  transition: transform var(--dur-1) var(--ease-out), box-shadow var(--dur-2), opacity var(--dur-2);
}
.send-btn:hover:not(:disabled) {
  transform: scale(1.05);
}
.send-btn:active:not(:disabled) {
  transform: scale(0.96);
}
.send-btn:disabled {
  opacity: 0.42;
  cursor: not-allowed;
  box-shadow: none;
}
.send-spin {
  width: 15px;
  height: 15px;
  border: 2px solid rgba(255, 255, 255, 0.35);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
}
.comp-hint {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 7px;
  padding: 0 8px;
  font-size: 11px;
  color: var(--c-text-3);
  white-space: nowrap;
}
.state-txt {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.state-txt i {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--c-text-3);
}
.state-txt.running i {
  background: var(--c-cyan);
  animation: breathe 1.1s ease-in-out infinite;
}

/* 右栏 */
.right-side {
  width: 292px;
  border-left: 1px solid var(--c-line);
  background: rgba(255, 255, 255, 0.5);
}
.tabs {
  position: relative;
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 12px 12px 8px;
  border-bottom: 1px solid var(--c-line);
}
.tab {
  padding: 6px 11px;
  border-radius: var(--r-sm);
  font-size: 12.5px;
  font-weight: 650;
  color: var(--c-text-3);
  white-space: nowrap;
  transition: background var(--dur-1), color var(--dur-1);
}
.tab:hover {
  color: var(--c-text-2);
  background: var(--c-bg-2);
}
.tab.on {
  color: var(--c-brand-deep);
  background: var(--c-brand-soft);
}
.close {
  margin-left: auto;
}
.panel-body {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}
.pane {
  height: 100%;
  overflow-y: auto;
  padding: 12px;
}

.panel-open {
  position: absolute;
  right: 12px;
  top: 12px;
  z-index: 30;
  background: var(--c-surface);
  border: 1px solid var(--c-line);
  box-shadow: var(--sh-2);
}

.slide-enter-from,
.slide-leave-to {
  opacity: 0;
  transform: translateX(24px);
}
.slide-enter-active,
.slide-leave-active {
  transition: opacity var(--dur-2) var(--ease-out), transform var(--dur-2) var(--ease-out);
}

/* 拖拽遮罩 */
.drop-mask {
  position: fixed;
  inset: 0;
  z-index: 300;
  background: rgba(85, 99, 255, 0.09);
  backdrop-filter: blur(3px);
  display: grid;
  place-items: center;
}
.drop-box {
  padding: 32px 52px;
  background: var(--c-surface);
  border: 2px dashed var(--c-brand);
  border-radius: var(--r-xl);
  text-align: center;
  box-shadow: var(--sh-4);
}
.drop-ico {
  font-size: 38px;
}
.drop-box p {
  margin-top: 8px;
  font-size: 16px;
  font-weight: 700;
  color: var(--c-brand-deep);
}
.drop-box small {
  color: var(--c-text-3);
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
.fade-enter-active,
.fade-leave-active {
  transition: opacity var(--dur-2);
}
.fold-enter-from,
.fold-leave-to {
  opacity: 0;
  transform: translateY(-5px);
}
.fold-enter-active,
.fold-leave-active {
  transition: opacity var(--dur-2) var(--ease-out), transform var(--dur-2) var(--ease-out);
}

/* 断点：1280–1440 收敛次要信息，窄屏折叠侧栏（对齐评审验收线） */
@media (max-width: 1440px) {
  .search-label {
    display: none;
  }
  .search-btn {
    padding: 7px 9px;
  }
  .right-side {
    width: 274px;
  }
}
@media (max-width: 1240px) {
  .left-side {
    display: none;
  }
  .brand small {
    display: none;
  }
}
@media (max-width: 1040px) {
  .right-side {
    position: absolute;
    right: 0;
    top: 0;
    bottom: 0;
    z-index: 40;
    box-shadow: var(--sh-4);
    background: var(--c-surface);
  }
  .sug {
    grid-template-columns: 1fr;
  }
}
</style>
