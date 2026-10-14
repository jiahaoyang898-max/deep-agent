<script setup lang="ts">
/**
 * 登录页 · 冰川观测站
 * ------------------------------------------------------------
 * 只负责「登录」。注册已拆到独立的 RegisterView.vue，两页通过 App.vue
 * 的轻量视图开关互相跳转（项目无 vue-router）。
 * 背景层 / HUD / 玻璃壳 / 字段与按钮语言统一由 CoverShell + cover.css 提供，
 * 本页只保留登录独有的「演示账号」块与「记住用户名」。
 */
import { ref, computed, nextTick, onMounted } from 'vue'
import { authApi, setAuth } from '../api'
import { toast } from '../toasts'
import CoverShell from '../components/CoverShell.vue'

const emit = defineEmits<{
  (e: 'authed', username: string): void
  (e: 'to-register'): void
}>()

const username = ref('')
const password = ref('')
const showPwd = ref(false)
const remember = ref(localStorage.getItem('das_remember') === '1')
const loading = ref(false)
const errorMsg = ref('')
const shakeKey = ref(0)
const submitRef = ref<HTMLButtonElement | null>(null)

/** 演示账号：由后端 auth 服务真实注册，可直接登录 */
const DEMO = { user: 'demo', pass: 'demo123456' }

/**
 * 演示账号开关：由构建期环境变量控制。
 * 未设置 → 显示（保持 8080 演示环境现状）；显式设为 'false' → 隐藏整块演示账号。
 */
const SHOW_DEMO = import.meta.env.VITE_SHOW_DEMO !== 'false'

const REMEMBER_KEY = 'das_last_user'

onMounted(() => {
  if (remember.value) username.value = localStorage.getItem(REMEMBER_KEY) || ''
})

const canSubmit = computed(() => {
  if (loading.value) return false
  if (username.value.trim().length < 2) return false
  if (password.value.length < 6) return false
  return true
})

function fillDemo() {
  username.value = DEMO.user
  password.value = DEMO.pass
  errorMsg.value = ''
  toast('已填入演示账号，点击「进入工作台」', 'success')
  nextTick(() => submitRef.value?.focus())
}

function fail(msg: string) {
  errorMsg.value = msg
  shakeKey.value++
}

async function submit() {
  errorMsg.value = ''
  if (!canSubmit.value) return
  loading.value = true
  try {
    const res = await authApi.login(username.value.trim(), password.value)
    setAuth(res.data.token, res.data.username)
    if (remember.value) {
      localStorage.setItem('das_remember', '1')
      localStorage.setItem(REMEMBER_KEY, res.data.username)
    } else {
      localStorage.removeItem('das_remember')
      localStorage.removeItem(REMEMBER_KEY)
    }
    await nextTick()
    emit('authed', res.data.username)
  } catch (e: any) {
    fail(e.response?.data?.detail || '网络异常，请稍后重试')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <CoverShell>
    <section class="card" :key="shakeKey" :class="{ shake: errorMsg, busy: loading }">
      <span class="brk tl" aria-hidden="true"></span>
      <span class="brk tr" aria-hidden="true"></span>
      <span class="brk bl" aria-hidden="true"></span>
      <span class="brk br" aria-hidden="true"></span>
      <span class="statusline" aria-hidden="true"></span>

      <div class="card-head">
        <p class="eyebrow"><span class="tick"></span>SECURE ACCESS</p>
        <h1>登录</h1>
        <p class="lead">接入工作台，继续你的调研会话</p>
      </div>

      <div class="card-body">
        <!-- 左列：字段 -->
        <form class="col-fields" novalidate @submit.prevent="submit">
          <div class="item" style="--i: 0">
            <label class="label" for="u">用户名</label>
            <div class="pill">
              <svg class="pi" viewBox="0 0 20 20" fill="none" aria-hidden="true">
                <circle cx="10" cy="6.6" r="3.4" stroke="currentColor" stroke-width="1.5" />
                <path d="M3.6 17c.6-3.2 3.2-4.9 6.4-4.9s5.8 1.7 6.4 4.9" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
              </svg>
              <input
                id="u"
                v-model="username"
                type="text"
                placeholder="至少 2 个字符"
                autocomplete="username"
                maxlength="32"
              />
            </div>
          </div>

          <div class="item" style="--i: 1">
            <label class="label" for="p">密码</label>
            <div class="pill">
              <svg class="pi" viewBox="0 0 20 20" fill="none" aria-hidden="true">
                <rect x="4.2" y="8.8" width="11.6" height="8.2" rx="2.4" stroke="currentColor" stroke-width="1.5" />
                <path d="M7 8.8V6.6a3 3 0 0 1 6 0v2.2" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
              </svg>
              <input
                id="p"
                v-model="password"
                :type="showPwd ? 'text' : 'password'"
                placeholder="至少 6 位"
                autocomplete="current-password"
                maxlength="64"
              />
              <button
                class="eye"
                type="button"
                :title="showPwd ? '隐藏密码' : '显示密码'"
                :aria-label="showPwd ? '隐藏密码' : '显示密码'"
                @click="showPwd = !showPwd"
              >
                <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
                  <path d="M1.8 10S4.9 4.8 10 4.8 18.2 10 18.2 10 15.1 15.2 10 15.2 1.8 10 1.8 10Z" stroke="currentColor" stroke-width="1.5" />
                  <circle cx="10" cy="10" r="2.3" stroke="currentColor" stroke-width="1.5" />
                  <path v-if="!showPwd" d="M3.4 3.4l13.2 13.2" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" />
                </svg>
              </button>
            </div>
          </div>

          <label class="remember">
            <input v-model="remember" type="checkbox" />
            <span class="box" aria-hidden="true">
              <svg viewBox="0 0 14 14" fill="none"><path d="M3 7.4l2.6 2.6L11 4.6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" /></svg>
            </span>
            <span>记住用户名</span>
          </label>

          <transition name="err">
            <p v-if="errorMsg" class="err" role="alert">
              <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
                <path d="M10 3.2l7.2 12.6H2.8L10 3.2Z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round" />
                <path d="M10 8.2v3.4M10 13.6h.01" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" />
              </svg>
              {{ errorMsg }}
            </p>
          </transition>
        </form>

        <!-- 右列：操作 -->
        <div class="col-actions">
          <button
            ref="submitRef"
            class="cta"
            type="button"
            :disabled="!canSubmit"
            @click="submit"
          >
            <span v-if="loading" class="spin" aria-hidden="true"></span>
            <span>{{ loading ? '正在验证…' : '进入工作台' }}</span>
            <svg v-if="!loading" class="arrow" viewBox="0 0 20 20" fill="none" aria-hidden="true">
              <path d="M4 10h11M10.5 5.5L15 10l-4.5 4.5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
          </button>

          <template v-if="SHOW_DEMO">
            <div class="or"><span>或</span></div>

            <div class="demo">
              <div class="demo-head">
                <span class="demo-tag">演示账号</span>
                <button class="fill" type="button" @click="fillDemo">一键填入</button>
              </div>
              <dl class="demo-cred mono">
                <div><dt>USER</dt><dd>{{ DEMO.user }}</dd></div>
                <div><dt>PASS</dt><dd>{{ DEMO.pass }}</dd></div>
              </dl>
            </div>
          </template>

          <p class="switch">
            还没有账号？
            <a href="#" @click.prevent="emit('to-register')">免费注册</a>
          </p>
        </div>
      </div>
    </section>
  </CoverShell>
</template>

<style scoped>
/* 登录页独有：演示账号块（注册页不放，避免重复） */
.demo {
  padding: 14px 15px 15px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.07);
  border: 1px solid rgba(255, 255, 255, 0.14);
}
.demo-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 11px;
}
.demo-tag {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  font-size: 11.5px;
  font-weight: 600;
  color: var(--on-glass-2);
}
.demo-tag::before {
  content: "";
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: #7dd3fc;
  box-shadow: 0 0 0 3px rgba(125, 211, 252, 0.18);
}
.fill {
  padding: 6px 13px;
  border-radius: 999px;
  font-size: 11.5px;
  font-weight: 600;
  color: #fff;
  background: rgba(255, 255, 255, 0.14);
  border: 1px solid rgba(255, 255, 255, 0.22);
  transition: background 0.18s, transform 0.18s var(--ease-expo);
}
.fill:hover { background: rgba(255, 255, 255, 0.24); }
.fill:active { transform: scale(0.97); }

.demo-cred {
  display: flex;
  gap: 20px;
}
.demo-cred > div {
  display: flex;
  align-items: baseline;
  gap: 8px;
  min-width: 0;
}
.demo-cred dt {
  font-size: 10px;
  letter-spacing: 0.14em;
  color: rgba(255, 255, 255, 0.68);
}
.demo-cred dd {
  font-size: 12.5px;
  color: #fff;
  letter-spacing: 0.02em;
}

@media (max-width: 620px) {
  .demo-cred { flex-direction: column; gap: 6px; }
}
</style>
