<script setup lang="ts">
/** 产物面板：真实文件数据，按修改时间倒序；行本身是 <a>，键盘可达 */
import { computed } from 'vue'
import type { FileMeta } from '../api'
import { api } from '../api'
import { fileMeta, formatSize, relativeTime } from '../types'

const props = defineProps<{
  files: FileMeta[]
  loading: boolean
}>()

const items = computed(() =>
  props.files.map((f) => {
    const m = fileMeta(f.name)
    return {
      ...f,
      url: api.downloadUrl(f.path),
      icon: m.icon,
      kind: m.kind,
      tone: m.tone,
      sizeText: formatSize(f.size),
      timeText: relativeTime(f.mtime * 1000),
    }
  }),
)
</script>

<template>
  <div class="file-panel">
    <div class="panel-head">
      <span>产物文件</span>
      <span class="count num">{{ files.length }}</span>
    </div>

    <div class="list" role="list">
      <template v-if="loading">
        <div v-for="i in 4" :key="i" class="skel">
          <div class="skeleton s-ico"></div>
          <div class="s-lines">
            <div class="skeleton s-l1"></div>
            <div class="skeleton s-l2"></div>
          </div>
        </div>
      </template>

      <div v-else-if="!files.length" class="empty">
        <div class="empty-ico" aria-hidden="true">🗂️</div>
        <p>暂无产物</p>
        <small>智能体生成的 Markdown / PDF 会实时落到这里</small>
      </div>

      <transition-group v-else name="fi" tag="div">
        <a
          v-for="f in items"
          :key="f.path"
          class="file-row glowline"
          role="listitem"
          :href="f.url"
          target="_blank"
          rel="noopener"
          :title="`下载 ${f.name}（${f.sizeText}）`"
        >
          <span class="stripe" :style="{ background: f.tone }"></span>
          <span class="ico" aria-hidden="true">{{ f.icon }}</span>
          <span class="info">
            <span class="name">{{ f.name }}</span>
            <span class="meta">
              <span class="chip">{{ f.kind }}</span>
              <span class="num">{{ f.sizeText }}</span>
              <span class="sep">·</span>
              <span class="num">{{ f.timeText }}</span>
            </span>
          </span>
          <span class="dl" aria-hidden="true">↓</span>
        </a>
      </transition-group>
    </div>
  </div>
</template>

<style scoped>
.file-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
}
.panel-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 2px 2px 12px;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.08em;
  color: var(--c-text-3);
  text-transform: uppercase;
}
.count {
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
.list {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding-right: 2px;
}

.skel {
  display: flex;
  gap: 10px;
  padding: 10px 6px;
}
.s-ico {
  width: 32px;
  height: 32px;
  border-radius: var(--r-sm);
  flex: 0 0 auto;
}
.s-lines {
  flex: 1;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 7px;
}
.s-l1 {
  height: 11px;
  width: 78%;
}
.s-l2 {
  height: 8px;
  width: 46%;
}

.empty {
  text-align: center;
  padding: 40px 10px;
}
.empty-ico {
  font-size: 34px;
  opacity: 0.75;
  margin-bottom: 10px;
}
.empty p {
  font-size: 13px;
  font-weight: 600;
  color: var(--c-text-2);
}
.empty small {
  font-size: 11.5px;
  color: var(--c-text-3);
  line-height: 1.7;
}

.file-row {
  position: relative;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 11px 10px 14px;
  background: var(--c-surface-2);
  border: 1px solid var(--c-line);
  border-radius: var(--r-md);
  overflow: hidden;
  transition: transform var(--dur-2) var(--ease-out), border-color var(--dur-2);
}
.file-row:hover {
  transform: translateY(-1px);
  border-color: var(--c-line-strong);
}
.stripe {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
}
.ico {
  font-size: 18px;
  flex: 0 0 auto;
}
.info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.name {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--c-ink);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.meta {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: var(--c-text-3);
  white-space: nowrap;
  overflow: hidden;
}
.meta .chip {
  padding: 1px 6px;
  font-size: 11px;
}
.sep {
  opacity: 0.6;
}
.dl {
  color: var(--c-brand-text);
  font-size: 14px;
  opacity: 0;
  transition: opacity var(--dur-1);
}
.file-row:hover .dl,
.file-row:focus-visible .dl {
  opacity: 1;
}

.fi-enter-from {
  opacity: 0;
  transform: translateX(14px);
}
.fi-enter-active {
  transition: opacity var(--dur-3) var(--ease-out), transform var(--dur-3) var(--ease-out);
}
</style>
