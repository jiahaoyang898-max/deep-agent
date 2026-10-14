<script setup lang="ts">
/**
 * 封面页共用外壳「冰川观测站」
 * ------------------------------------------------------------
 * 登录页 / 注册页共用的：摄影背景 + 冷调遮罩 + 测绘网格 + 胶片颗粒、
 * 顶部 HUD（品牌标识 / 本地部署读数 / 实时时钟）、底部刻度尺。
 * 中央玻璃卡由使用方通过默认插槽传入，保持两页构图各自独立。
 * 样式统一在 src/cover.css 的 `.cover` 命名空间下。
 */
import { ref, onMounted, onUnmounted } from 'vue'

/* ---------- 顶部 HUD 实时时钟 ---------- */
const clock = ref('--:--:--')
let timer: number | undefined
function tick() {
  const d = new Date()
  const p = (n: number) => String(n).padStart(2, '0')
  clock.value = `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}
onMounted(() => {
  tick()
  timer = window.setInterval(tick, 1000)
})
onUnmounted(() => {
  if (timer) window.clearInterval(timer)
})
</script>

<template>
  <div class="cover">
    <!-- ① 摄影背景 + 冷调遮罩 + 测绘网格 + 胶片颗粒 -->
    <div class="backdrop" aria-hidden="true">
      <div class="photo"></div>
      <div class="scrim"></div>
      <div class="grid"></div>
      <div class="grain"></div>
    </div>

    <!-- ② 顶部 HUD -->
    <header class="hud" aria-hidden="true">
      <div class="hud-left">
        <svg class="mark" viewBox="0 0 32 32" fill="none">
          <circle cx="16" cy="16" r="11.5" stroke="currentColor" stroke-width="1.4" opacity=".55" />
          <circle cx="16" cy="16" r="5" stroke="currentColor" stroke-width="1.4" />
          <path d="M16 1.5v7M16 23.5v7M1.5 16h7M23.5 16h7" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" />
          <circle cx="16" cy="16" r="1.9" fill="currentColor" />
        </svg>
        <span class="wordmark">
          <b>DEEP AGENT SEARCH</b>
          <small>深度医药市场调研智能体</small>
        </span>
      </div>

      <div class="hud-right">
        <span class="readout">
          <i class="dot" aria-hidden="true"></i>LOCAL · 数据不出内网
        </span>
        <span class="readout mono">{{ clock }}</span>
      </div>
    </header>

    <!-- ③ 中央舞台：玻璃卡由调用方提供 -->
    <main class="stage">
      <slot />
    </main>

    <!-- ④ 底部刻度尺 -->
    <footer class="foot" aria-hidden="true">
      <span class="ruler"></span>
      <span class="mono">v2.0 · 冰川观测站</span>
    </footer>
  </div>
</template>
