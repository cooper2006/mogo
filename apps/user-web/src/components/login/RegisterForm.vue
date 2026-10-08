<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import {
  listRegisterableDepartments,
  listRegisterableTenants,
  register,
  type RegisterableDepartment,
  type RegisterableTenant,
  type UserProfile,
} from '../../api/auth'
import { t } from '../../composables/i18n'

const emit = defineEmits<{
  (event: 'register-success', payload: { token: string; username: string; profile?: UserProfile }): void
  (event: 'switch-to-login'): void
}>()

const tenants = ref<RegisterableTenant[]>([])
const tenantsLoaded = ref(false)
const tenantsError = ref('')

const selectedMainId = ref('')
const departments = ref<RegisterableDepartment[]>([])
const departmentsLoaded = ref(false)
const selectedDepartmentId = ref('')

const nickname = ref('')
const email = ref('')
const password = ref('')
const confirmPassword = ref('')
const errorMessage = ref('')
const isSubmitting = ref(false)

// When only one enterprise tenant exists, hide the selector and auto-select it.
const singleTenant = computed(() => tenants.value.length === 1)
const showTenantSelector = computed(() => tenants.value.length > 1)
const activeMainId = computed(() => singleTenant.value ? tenants.value[0].mainId : selectedMainId.value)

async function loadTenants() {
  tenantsLoaded.value = false
  tenantsError.value = ''
  const result = await listRegisterableTenants()
  if (!result.ok || !result.tenants) {
    tenantsError.value = result.message || t('login.register_load_tenants_failed')
    tenants.value = []
  } else {
    tenants.value = result.tenants
  }
  tenantsLoaded.value = true
  if (singleTenant.value) {
    selectedMainId.value = tenants.value[0].mainId
  }
}

async function loadDepartments(mainId: string) {
  departmentsLoaded.value = false
  selectedDepartmentId.value = ''
  departments.value = []
  if (!mainId) return
  const result = await listRegisterableDepartments(mainId)
  if (result.ok && result.departments) {
    departments.value = result.departments
  }
  departmentsLoaded.value = true
}

onMounted(loadTenants)

// Reload departments whenever the effective tenant changes.
watch(activeMainId, (mainId) => {
  if (mainId) loadDepartments(mainId)
})

function resetError() {
  errorMessage.value = ''
}

function validate(): boolean {
  if (!singleTenant.value && !selectedMainId.value) {
    errorMessage.value = t('login.register_no_tenant')
    return false
  }
  const normalizedEmail = email.value.trim().toLowerCase()
  if (!normalizedEmail) {
    errorMessage.value = t('login.register_email_empty')
    return false
  }
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(normalizedEmail)) {
    errorMessage.value = t('login.register_email_invalid')
    return false
  }
  const pw = password.value
  if (pw.length < 8 || !/[A-Za-z]/.test(pw) || !/[0-9]/.test(pw)) {
    errorMessage.value = t('login.register_password_weak')
    return false
  }
  if (pw !== confirmPassword.value) {
    errorMessage.value = t('login.register_password_mismatch')
    return false
  }
  return true
}

async function submit() {
  resetError()
  if (!validate()) return

  isSubmitting.value = true
  const mainId = activeMainId.value
  const result = await register(
    mainId,
    email.value.trim().toLowerCase(),
    password.value,
    nickname.value.trim(),
    selectedDepartmentId.value,
  )
  isSubmitting.value = false

  if (!result.ok || !result.token) {
    errorMessage.value = result.message || t('api.auth.register_failed')
    return
  }
  emit('register-success', {
    token: result.token,
    username: email.value.trim().toLowerCase(),
    profile: result.profile,
  })
}
</script>

<template>
  <form class="space-y-4" @submit.prevent="submit">
    <div v-if="tenantsError" role="alert" class="rounded-2xl bg-rose-50 px-3 py-2 text-sm text-rose-600">
      {{ tenantsError }}
    </div>

    <div v-if="showTenantSelector" class="space-y-2">
      <label for="movo-register-tenant" class="text-sm font-medium text-slate-700">{{ t('login.register_org_label') }}</label>
      <select
        id="movo-register-tenant"
        v-model="selectedMainId"
        class="min-h-[44px] w-full rounded-2xl border border-slate-200 px-4 text-slate-900 outline-none focus:border-slate-400 focus-visible:ring-2 focus-visible:ring-slate-200"
        @change="resetError"
      >
        <option value="" disabled>{{ t('login.register_org_placeholder') }}</option>
        <option v-for="tenant in tenants" :key="tenant.mainId" :value="tenant.mainId">
          {{ tenant.orgName }}
        </option>
      </select>
    </div>

    <div v-if="singleTenant" class="rounded-2xl bg-slate-50 px-3 py-2 text-sm text-slate-600">
      {{ t('login.register_org_joined') }}：{{ tenants[0].orgName }}
    </div>

    <div v-if="departments.length > 1" class="space-y-2">
      <label for="movo-register-department" class="text-sm font-medium text-slate-700">{{ t('login.register_department_label') }}</label>
      <select
        id="movo-register-department"
        v-model="selectedDepartmentId"
        class="min-h-[44px] w-full rounded-2xl border border-slate-200 px-4 text-slate-900 outline-none focus:border-slate-400 focus-visible:ring-2 focus-visible:ring-slate-200"
        @change="resetError"
      >
        <option value="">{{ t('login.register_department_root') }}</option>
        <option v-for="dept in departments" :key="dept.id" :value="dept.id">
          {{ '　'.repeat(dept.depth) }}{{ dept.name }}
        </option>
      </select>
    </div>

    <div class="space-y-2">
      <label for="movo-register-nickname" class="text-sm font-medium text-slate-700">{{ t('login.register_nickname_label') }}</label>
      <input
        id="movo-register-nickname"
        v-model="nickname"
        type="text"
        autocomplete="nickname"
        class="min-h-[44px] w-full rounded-2xl border border-slate-200 px-4 text-slate-900 outline-none transition-colors focus:border-slate-400 focus-visible:ring-2 focus-visible:ring-slate-200"
        :placeholder="t('login.register_nickname_placeholder')"
        @input="resetError"
      />
    </div>

    <div class="space-y-2">
      <label for="movo-register-email" class="text-sm font-medium text-slate-700">{{ t('login.register_email_label') }}</label>
      <input
        id="movo-register-email"
        v-model="email"
        type="email"
        autocomplete="email"
        class="min-h-[44px] w-full rounded-2xl border border-slate-200 px-4 text-slate-900 outline-none transition-colors focus:border-slate-400 focus-visible:ring-2 focus-visible:ring-slate-200"
        :placeholder="t('login.register_email_placeholder')"
        @input="resetError"
      />
    </div>

    <div class="space-y-2">
      <label for="movo-register-password" class="text-sm font-medium text-slate-700">{{ t('login.register_password_label') }}</label>
      <input
        id="movo-register-password"
        v-model="password"
        type="password"
        autocomplete="new-password"
        class="min-h-[44px] w-full rounded-2xl border border-slate-200 px-4 text-slate-900 outline-none transition-colors focus:border-slate-400 focus-visible:ring-2 focus-visible:ring-slate-200"
        :placeholder="t('login.register_password_placeholder')"
        @input="resetError"
      />
    </div>

    <div class="space-y-2">
      <label for="movo-register-confirm" class="text-sm font-medium text-slate-700">{{ t('login.register_confirm_label') }}</label>
      <input
        id="movo-register-confirm"
        v-model="confirmPassword"
        type="password"
        autocomplete="new-password"
        class="min-h-[44px] w-full rounded-2xl border border-slate-200 px-4 text-slate-900 outline-none transition-colors focus:border-slate-400 focus-visible:ring-2 focus-visible:ring-slate-200"
        :placeholder="t('login.register_confirm_placeholder')"
        @input="resetError"
      />
    </div>

    <p v-if="errorMessage" role="alert" class="rounded-2xl bg-rose-50 px-3 py-2 text-sm text-rose-600">
      {{ errorMessage }}
    </p>

    <button
      type="submit"
      class="min-h-[44px] w-full rounded-2xl bg-slate-900 px-4 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-70"
      :disabled="isSubmitting || !tenantsLoaded"
    >
      {{ isSubmitting ? t('login.register_submitting') : t('login.register_submit') }}
    </button>

    <p class="text-center text-sm text-slate-500">
      {{ t('login.register_have_account') }}
      <button type="button" class="font-medium text-slate-900 underline-offset-2 hover:underline" @click="emit('switch-to-login')">
        {{ t('login.register_to_login') }}
      </button>
    </p>
  </form>
</template>
