<script setup lang="ts">
/**
 * 注册页 · 冰川观测站
 * ------------------------------------------------------------
 * 与登录页共用同一套视觉语言（背景层 / HUD / 玻璃壳 / 字段与按钮），
 * 由 CoverShell + cover.css 提供，本页只写注册独有的内容。
 *
 * 构图区分度：保持与登录页一致的左右分栏骨架（切换时卡片几何位置不变，
 * 不会产生"换页跳档"），但右列由「演示账号」换成了功能性的
 * 「注册须知 + 密码规则实时勾选清单」——差异来自内容与状态反馈，
 * 而不是靠改版式来制造区别。
 *
 * 流程真实可用：authApi.register → authApi.login → setAuth → emit('authed')。
 */
import { ref, computed, nextTick } from 'vue'
import { authApi, setAuth } from '../api'
import { toast } from '../toasts'
import CoverShell from '../components/CoverShell.vue'

const emit = defineEmits<{
  (e: 'authed', username: string): void
  (e: 'to-login'): void
}>()

const username = ref('')
const password = ref('')
const confirmPwd = ref('')
const showPwd = ref(false)
const loading = ref(false)
const errorMsg = ref('')
const shakeKey = ref(0)

/** 用户名建议字符集：字母/数字/下划线，便于后端与后续登录输入 */
const nameOk = computed(() => /^[A-Za-z0-9_]{2,32}$/.test(username.value.trim()))
const confirmOk = computed(() => !!confirmPwd.value && confirmPwd.value === password.value)

/* ---------- 密码强度（与登录页同一套 4 档逻辑与配色） ---------- */
const pwdStrength = computed(() => {
  const p = password.value
  if (!p) return 0
  let s = 0
  if (p.length >= 8) s++
  if (/[A-Z]/.test(p) && /[a-z]/.test(p)) s++
  if (/\d/.test(p)) s++
  if (/[^A-Za-z0-9]/.test(p)) s++
  return s
})
const strengthLabel = computed(() => ['太短啦', '较弱', '一般', '良好', '很强'][pwdStrength.value])
const strengthColor = computed(
  () =>
    ['rgba(255,255,255,.28)', 'var(--cv-rose)', 'var(--cv-amber)', 'var(--cv-brand-lt)', 'var(--cv-grass)'][
      pwdStrength.value
    ],
)

/* ---------- 密码规则实时勾选清单 ---------- */
const rules = computed(() => [
  { key: 'len', text: '长度至少 6 位', ok: password.value.length >= 6 },
  { key: 'alpha', text: '包含字母', ok: /[A-Za-z]/.test(password.value) },
  { key: 'digit', text: '包含数字', ok: /\d/.test(password.value) },
  { key: 'strong', text: '含大写或符号（更安全）', ok: /[A-Z]/.test(password.value) || /[^A-Za-z0-9]/.test(password.value) },
  { key: 'match', text: '两次输入一致', ok: confirmOk.value },
])
const rulesDone = computed(() => rules.value.filter((r) => r.ok).length)

const canSubmit = computed(() => {
  if (loading.value) return false
  if (username.value.trim().length < 2) return false
  if (password.value.length < 6) return false
  return true
})

function fail(msg: string) {
  errorMsg.value = msg
  shakeKey.value++
}

async function submit() {
  errorMsg.value = ''
  if (!canSubmit.value) return
  if (!confirmOk.value) {
    fail('两次输入的密码不一致')
    return
  }
  loading.value = true
  try {
    await authApi.register(username.value.trim(), password.value)
    toast('注册成功，已自动登录', 'success')
    const res = await authApi.login(username.value.trim(), password.value)
    setAuth(res.data.token, res.data.username)
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
        <p class="eyebrow"><span class="tick"></span>NEW OPERATOR</p>
        <h1>创建账号</h1>
        <p class="lead">填写账号信息，即刻开始你的调研会话</p>
      </div>

      <div class="card-body">
        <!-- 左列：字段 -->
        <form class="col-fields" novalidate @submit.prevent="submit">
          <div class="item" style="--i: 0">
            <label class="label" for="ru">用户名</label>
            <div class="pill">
              <svg class="pi" viewBox="0 0 20 20" fill="none" aria-hidden="true">
                <circle cx="10" cy="6.6" r="3.4" stroke="currentColor" stroke-width="1.5" />
                <path d="M3.6 17c.6-3.2 3.2-4.9 6.4-4.9s5.8 1.7 6.4 4.9" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
              </svg>
              <input
                id="ru"
                v-model="username"
                type="text"
                placeholder="2–32 位字母 / 数字 / 下划线"
                autocomplete="username"
                maxlength="32"
              />
              <span v-if="username && nameOk" class="okmark" aria-hidden="true">
                <svg viewBox="0 0 16 16" fill="none"><path d="M3.4 8.4l3 3L12.6 5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" /></svg>
              </span>
            </div>
          </div>

          <div class="item" style="--i: 1">
            <label class="label" for="rp">密码</label>
            <div class="pill">
              <svg class="pi" viewBox="0 0 20 20" fill="none" aria-hidden="true">
                <rect x="4.2" y="8.8" width="11.6" height="8.2" rx="2.4" stroke="currentColor" stroke-width="1.5" />
                <path d="M7 8.8V6.6a3 3 0 0 1 6 0v2.2" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
              </svg>
              <input
                id="rp"
                v-model="password"
                :type="showPwd ? 'text' : 'password'"
                placeholder="至少 6 位"
                autocomplete="new-password"
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
            <div v-if="password" class="strength">
              <span class="bars">
                <i v-for="i in 4" :key="i" :style="{ background: i <= pwdStrength ? strengthColor : 'rgba(255,255,255,.14)' }"></i>
              </span>
              <span class="s-label" :style="{ color: strengthColor }">{{ strengthLabel }}</span>
            </div>
          </div>

          <div class="item" style="--i: 2">
            <label class="label" for="rc">确认密码</label>
            <div class="pill">
              <svg class="pi" viewBox="0 0 20 20" fill="none" aria-hidden="true">
                <path d="M10 2.6l6 2.6v5c0 3.5-2.5 6.2-6 7.2-3.5-1-6-3.7-6-7.2v-5l6-2.6Z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round" />
                <path v-if="confirmOk" d="M7.4 10.1l1.8 1.8 3.4-3.6" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" />
              </svg>
              <input
                id="rc"
                v-model="confirmPwd"
                :type="showPwd ? 'text' : 'password'"
                placeholder="再输入一次"
                autocomplete="new-password"
                maxlength="64"
              />
            </div>
          </div>

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

        <!-- 右列：注册须知 + 密码规则实时清单 -->
        <div class="col-actions">
          <button
            class="cta"
            type="button"
            :disabled="!canSubmit"
            @click="submit"
          >
            <span v-if="loading" class="spin" aria-hidden="true"></span>
            <span>{{ loading ? '正在创建…' : '注册并进入' }}</span>
            <svg v-if="!loading" class="arrow" viewBox="0 0 20 20" fill="none" aria-hidden="true">
              <path d="M4 10h11M10.5 5.5L15 10l-4.5 4.5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
          </button>

          <div class="or"><span>账号要求</span></div>

          <div class="brief">
            <div class="brief-head">
              <span class="brief-tag">注册须知</span>
              <span class="brief-count mono">{{ rulesDone }}/{{ rules.length }}</span>
            </div>
            <ul class="rules">
              <li v-for="r in rules" :key="r.key" :class="{ ok: r.ok }">
                <span class="r-box" aria-hidden="true">
                  <svg viewBox="0 0 14 14" fill="none"><path d="M3 7.4l2.6 2.6L11 4.6" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" /></svg>
                </span>
                <span class="r-text">{{ r.text }}</span>
              </li>
            </ul>
            <p class="brief-note">账号在本地 auth 服务创建，数据不出内网。</p>
          </div>

          <p class="switch">
            已有账号？
            <a href="#" @click.prevent="emit('to-login')">去登录</a>
          </p>
        </div>
      </div>
    </section>
  </CoverShell>
</template>

<style scoped>
/* 用户名合规时的小勾：只作正向反馈，不打断输入 */
.okmark {
  display: grid;
  place-items: center;
  width: 20px;
  height: 20px;
  margin-right: 14px;
  flex: 0 0 auto;
  border-radius: 50%;
  color: var(--cv-grass);
}
.okmark svg { width: 14px; height: 14px; }

/* 注册须知面板：与登录页演示账号块同一套玻璃语言 */
.brief {
  padding: 14px 15px 15px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.07);
  border: 1px solid rgba(255, 255, 255, 0.14);
}
.brief-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 12px;
}
.brief-tag {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  font-size: 11.5px;
  font-weight: 600;
  color: var(--on-glass-2);
}
.brief-tag::before {
  content: "";
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--cv-cyan);
  box-shadow: 0 0 0 3px rgba(34, 211, 238, 0.18);
}
.brief-count {
  font-size: 11px;
  letter-spacing: 0.06em;
  color: var(--on-glass-3);
}

.rules {
  display: flex;
  flex-direction: column;
  gap: 9px;
  list-style: none;
}
.rules li {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12.5px;
  color: var(--on-glass-3);
  transition: color 0.2s;
}
.rules li.ok { color: var(--on-glass); }
.r-box {
  display: grid;
  place-items: center;
  width: 17px;
  height: 17px;
  flex: 0 0 auto;
  border-radius: 5px;
  border: 1.5px solid rgba(255, 255, 255, 0.34);
  background: rgba(255, 255, 255, 0.06);
  color: var(--c-ink);
  transition: background 0.2s var(--ease-expo), border-color 0.2s;
}
.r-box svg {
  width: 11px;
  height: 11px;
  opacity: 0;
  transform: scale(0.6);
  transition: opacity 0.18s, transform 0.18s var(--ease-expo);
}
.rules li.ok .r-box {
  background: var(--cv-grass);
  border-color: var(--cv-grass);
}
.rules li.ok .r-box svg {
  opacity: 1;
  transform: scale(1);
}
.r-text { min-width: 0; }

.brief-note {
  margin-top: 12px;
  padding-top: 11px;
  border-top: 1px solid rgba(255, 255, 255, 0.1);
  font-size: 11.5px;
  line-height: 1.6;
  /* 深色玻璃上 0.42 白实测仅 3.3:1，提到 0.68 后过 AA */
  color: rgba(255, 255, 255, 0.68);
}
</style>
