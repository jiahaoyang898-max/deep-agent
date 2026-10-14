<script setup lang="ts">
/**
 * 命令面板（Ctrl / ⌘ + K）
 * 只收录真实可执行的动作，不做无定义控件。
 */
import { ref, computed, watch, nextTick } from 'vue'

export interface Command {
  id: string
  label: string
  hint?: string
  group: string
  keyHint?: string
  run: () => void
}

const props = defineProps<{
  open: boolean
  commands: Command[]
}>()

const emit = defineEmits<{ (e: 'close'): void }>()

const keyword = ref('')
const cursor = ref(0)
const inputRef = ref<HTMLInputElement | null>(null)

const grouped = computed(() => {
  const k = keyword.value.trim().toLowerCase()
  const filtered = k
    ? props.commands.filter(
        (c) => c.label.toLowerCase().includes(k) || c.group.toLowerCase().includes(k),
      )
    : props.commands
  const map = new Map<string, Command[]>()
  filtered.forEach((c) => {
    if (!map.has(c.group)) map.set(c.group, [])
    map.get(c.group)!.push(c)
  })
  return [...map.entries()].map(([group, items]) => ({ group, items }))
})

const flat = computed(() => grouped.value.flatMap((g) => g.items))

watch(
  () => props.open,
  async (v) => {
    if (v) {
      keyword.value = ''
      cursor.value = 0
      await nextTick()
      inputRef.value?.focus()
    }
  },
)

watch(keyword, () => {
  cursor.value = 0
})

function move(step: number) {
  if (!flat.value.length) return
  cursor.value = (cursor.value + step + flat.value.length) % flat.value.length
}

function exec(cmd?: Command) {
  const target = cmd || flat.value[cursor.value]
  if (!target) return
  target.run()
  emit('close')
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'ArrowDown') {
    e.preventDefault()
    move(1)
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    move(-1)
  } else if (e.key === 'Enter') {
    e.preventDefault()
    exec()
  } else if (e.key === 'Escape') {
    emit('close')
  }
}

function indexOf(cmd: Command): number {
  return flat.value.indexOf(cmd)
}
</script>

<template>
  <transition name="palette">
    <div v-if="open" class="palette-mask" @click.self="emit('close')" role="presentation">
      <div
        class="palette glass glowline on"
        role="dialog"
        aria-modal="true"
        aria-label="命令面板"
        @keydown="onKeydown"
      >
        <div class="palette-input">
          <span class="ico" aria-hidden="true">⌘</span>
          <input
            ref="inputRef"
            v-model="keyword"
            type="text"
            placeholder="搜索动作：新会话 / 切换历史 / 文件面板 / 退出登录"
            aria-label="搜索命令"
          />
          <span class="kbd">ESC</span>
        </div>

        <div class="palette-list" role="listbox" aria-label="命令列表">
          <template v-if="flat.length">
            <div v-for="g in grouped" :key="g.group" class="group">
              <div class="group-title">{{ g.group }}</div>
              <button
                v-for="c in g.items"
                :key="c.id"
                class="cmd"
                :class="{ active: indexOf(c) === cursor }"
                role="option"
                :aria-selected="indexOf(c) === cursor"
                @click="exec(c)"
                @mouseenter="cursor = indexOf(c)"
              >
                <span class="cmd-label">{{ c.label }}</span>
                <span v-if="c.hint" class="cmd-hint">{{ c.hint }}</span>
                <span v-if="c.keyHint" class="kbd">{{ c.keyHint }}</span>
              </button>
            </div>
          </template>
          <div v-else class="empty">
            <span aria-hidden="true">🔍</span> 没有匹配的动作
          </div>
        </div>

        <div class="palette-foot">
          <span><span class="kbd">↑</span><span class="kbd">↓</span> 选择</span>
          <span><span class="kbd">↵</span> 执行</span>
          <span class="total num">{{ flat.length }} 项</span>
        </div>
      </div>
    </div>
  </transition>
</template>

<style scoped>
.palette-mask {
  position: fixed;
  inset: 0;
  z-index: 400;
  background: rgba(15, 20, 36, 0.32);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding-top: 14vh;
}
.palette {
  width: min(560px, 92vw);
  border-radius: var(--r-lg);
  box-shadow: var(--sh-4);
  overflow: hidden;
  background: var(--c-surface);
}

.palette-input {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 16px;
  border-bottom: 1px solid var(--c-line);
}
.palette-input .ico {
  color: var(--c-brand);
  font-size: 15px;
}
.palette-input input {
  flex: 1;
  border: none;
  background: transparent;
  font-size: 14.5px;
  outline: none;
}
.palette-input input::placeholder {
  color: var(--c-text-3);
}

.palette-list {
  max-height: 46vh;
  overflow-y: auto;
  padding: 8px;
}
.group + .group {
  margin-top: 6px;
}
.group-title {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--c-text-3);
  padding: 8px 10px 4px;
}
.cmd {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-radius: var(--r-sm);
  text-align: left;
  transition: background var(--dur-1);
}
.cmd.active {
  background: var(--c-brand-soft);
}
.cmd-label {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--c-text);
}
.cmd-hint {
  font-size: 12px;
  color: var(--c-text-3);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.cmd .kbd {
  margin-left: auto;
}
.empty {
  padding: 28px 10px;
  text-align: center;
  color: var(--c-text-3);
  font-size: 13px;
}

.palette-foot {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 9px 16px;
  border-top: 1px solid var(--c-line);
  background: var(--c-surface-2);
  font-size: 11.5px;
  color: var(--c-text-3);
}
.palette-foot .kbd {
  margin-right: 3px;
}
.palette-foot .total {
  margin-left: auto;
}

.palette-enter-from,
.palette-leave-to {
  opacity: 0;
}
.palette-enter-from .palette,
.palette-leave-to .palette {
  transform: translateY(-10px) scale(0.98);
}
.palette-enter-active,
.palette-leave-active {
  transition: opacity var(--dur-2) var(--ease-out);
}
.palette-enter-active .palette,
.palette-leave-active .palette {
  transition: transform var(--dur-2) var(--ease-out);
}
</style>
