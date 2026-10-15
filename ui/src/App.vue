<script setup lang="ts">
import { ref, onMounted } from 'vue'
import LoginView from './views/LoginView.vue'
import RegisterView from './views/RegisterView.vue'
import ChatView from './views/ChatView.vue'
import { toasts } from './toasts'
import { authApi, getToken, clearAuth, registerUnauthorizedHandler, getStoredUser } from './api'

type Stage = 'checking' | 'guest' | 'authed'
/** 未登录阶段的轻量视图开关（项目无 vue-router） */
type GuestView = 'login' | 'register'

const stage = ref<Stage>('checking')
const guestView = ref<GuestView>('login')
const username = ref(getStoredUser())

function enterApp(name: string) {
  username.value = name
  stage.value = 'authed'
  guestView.value = 'login'
}

function exitApp() {
  clearAuth()
  username.value = ''
  stage.value = 'guest'
}

onMounted(async () => {
  registerUnauthorizedHandler(exitApp)
  if (!getToken()) {
    stage.value = 'guest'
    return
  }
  try {
    const res = await authApi.me()
    enterApp(res.data.username)
  } catch {
    clearAuth()
    stage.value = 'guest'
  }
})
</script>

<template>
  <!-- 启动校验画面 -->
  <div v-if="stage === 'checking'" class="boot-screen">
    <div class="boot-logo">✦</div>
    <div class="boot-bar"><span></span></div>
  </div>

  <LoginView
    v-else-if="stage === 'guest' && guestView === 'login'"
    @authed="enterApp"
    @to-register="guestView = 'register'"
  />

  <RegisterView
    v-else-if="stage === 'guest'"
    @authed="enterApp"
    @to-login="guestView = 'login'"
  />

  <ChatView v-else :username="username" @logout="exitApp" />

  <!-- 全局 Toast -->
  <transition-group name="toast" tag="div" class="toast-wrap">
    <div v-for="t in toasts" :key="t.id" class="toast" :class="t.kind">
      <span class="toast-icon">
        {{ t.kind === 'success' ? '✓' : t.kind === 'error' ? '✕' : 'ⓘ' }}
      </span>
      {{ t.text }}
    </div>
  </transition-group>
</template>

<style scoped>
.boot-screen {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 20px;
  /* 登录页（cover.css 冰川观测站）与工作台现均为深色，闪屏统一用中性深底，
     避免「深→浅→深」的跳色；此处在 .page 之外，令牌仍是浅色值，故硬编码。 */
  background: #0a0d16;
}
.boot-logo {
  font-size: 38px;
  background: var(--c-grad);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  animation: breathe 1.5s ease-in-out infinite;
}
.boot-bar {
  width: 132px;
  height: 3px;
  border-radius: var(--r-full);
  /* 深底上的轨道：原 --c-bg-2 在 .page 外是浅色 #eceef7，会变成一条亮条 */
  background: rgba(255, 255, 255, 0.07);
  overflow: hidden;
}
.boot-bar span {
  display: block;
  width: 38%;
  height: 100%;
  border-radius: var(--r-full);
  background: var(--c-grad);
  animation: bootSlide 1.1s ease-in-out infinite;
}
@keyframes bootSlide {
  from {
    transform: translateX(-100%);
  }
  to {
    transform: translateX(360%);
  }
}

.toast-wrap {
  position: fixed;
  top: 18px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 999;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 9px;
  pointer-events: none;
}
.toast {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 10px 18px;
  border-radius: var(--r-full);
  background: var(--c-surface);
  border: 1px solid var(--c-line);
  box-shadow: var(--sh-3);
  font-size: 13px;
  font-weight: 600;
  color: var(--c-text);
  animation: popIn 0.3s var(--ease-spring) both;
}
.toast-icon {
  display: grid;
  place-items: center;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  color: #fff;
  font-size: 11px;
  flex: 0 0 auto;
}
.toast.success .toast-icon {
  background: var(--c-grass);
}
.toast.error .toast-icon {
  background: var(--c-rose);
}
.toast.info .toast-icon {
  background: var(--c-brand);
}
.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateY(-12px) scale(0.96);
}
.toast-enter-active,
.toast-leave-active {
  transition: opacity var(--dur-2) var(--ease-out), transform var(--dur-2) var(--ease-out);
}
</style>
