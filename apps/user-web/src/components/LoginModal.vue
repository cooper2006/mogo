<script setup lang="ts">
import { ref } from 'vue'
import PasswordLoginForm from './login/PasswordLoginForm.vue'
import RegisterForm from './login/RegisterForm.vue'
import DesktopLoginServerSwitch from './desktop/DesktopLoginServerSwitch.vue'
import { t } from '../composables/i18n'
import type { UserProfile } from '../api/auth'

defineProps<{
  open: boolean
  savedUsers: string[]
}>()

const emit = defineEmits<{
  (event: 'close'): void
  (event: 'login-success', payload: { token: string; username: string; profile?: UserProfile }): void
}>()

const mode = ref<'login' | 'register'>('login')

function handleAuthSuccess(payload: { token: string; username: string; profile?: UserProfile }) {
  emit('login-success', payload)
}
</script>

<template>
  <div v-if="open" class="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
    <div class="max-h-[calc(100vh-2rem)] w-full max-w-md overflow-y-auto rounded-3xl bg-white p-6 shadow-2xl">
      <div class="flex items-start justify-between gap-4">
        <div class="flex items-start gap-3">
          <img src="/movo-logo.png" alt="MOGO" class="mt-0.5 h-10 w-12 shrink-0 object-contain" />
          <div>
            <div class="text-xl font-semibold text-slate-900">{{ t('login.title') }}</div>
            <div class="mt-1 text-sm leading-5 text-slate-500">{{ t('login.password_desc') }}</div>
          </div>
        </div>
        <button
          class="rounded-full p-2 text-slate-400 transition-colors hover:bg-slate-100"
          :aria-label="t('login.close_aria')"
          @click="emit('close')"
        >
          <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
            <path d="M18 6 6 18" />
            <path d="m6 6 12 12" />
          </svg>
        </button>
      </div>

      <div class="mt-6 flex gap-1 rounded-2xl bg-slate-100 p-1">
        <button
          type="button"
          class="flex-1 rounded-xl px-4 py-2 text-sm font-medium transition-colors"
          :class="mode === 'login' ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-700'"
          @click="mode = 'login'"
        >
          {{ t('login.tab_login') }}
        </button>
        <button
          type="button"
          class="flex-1 rounded-xl px-4 py-2 text-sm font-medium transition-colors"
          :class="mode === 'register' ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-700'"
          @click="mode = 'register'"
        >
          {{ t('login.tab_register') }}
        </button>
      </div>

      <PasswordLoginForm
        v-if="mode === 'login'"
        class="mt-5"
        :suggested-username="savedUsers[0]"
        @login-success="handleAuthSuccess"
      />
      <RegisterForm
        v-else
        class="mt-5"
        @register-success="handleAuthSuccess"
        @switch-to-login="mode = 'login'"
      />
      <DesktopLoginServerSwitch />
    </div>
  </div>
</template>
