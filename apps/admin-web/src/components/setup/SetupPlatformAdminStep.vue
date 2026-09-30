<template>
  <div class="step-content">
    <div class="step-heading">
      <span class="step-kicker">{{ t('步骤 2 / 3') }}</span>
      <div class="section-heading">
        <span class="section-heading-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24">
            <path d="M12 3 4 7v6c0 4.4 3.4 7.6 8 8 4.6-.4 8-3.6 8-8V7l-8-4Z" />
            <path d="m9 12 2 2 4-4" />
          </svg>
        </span>
        <div>
          <h2>{{ t('创建平台超级管理员') }}</h2>
          <p>
            {{ t('平台超级管理员用于管理租户生命周期（创建、归档、清理），不查看租户内业务数据。引导流程不会创建任何租户。') }}
          </p>
        </div>
      </div>
    </div>

    <n-form label-placement="top">
      <n-form-item :label="t('平台管理员账号')">
        <n-input v-model:value="model.username" placeholder="platform" autocomplete="username" />
      </n-form-item>
      <n-form-item :label="t('平台管理员显示名')">
        <n-input v-model:value="model.displayName" :placeholder="t('平台管理员')" />
      </n-form-item>
      <n-form-item :label="t('平台管理员密码')">
        <n-input
          v-model:value="model.password"
          type="password"
          show-password-on="click"
          autocomplete="new-password"
        />
      </n-form-item>
    </n-form>

    <n-button block type="primary" size="large" :loading="submitting" @click="$emit('submit')">
      {{ t('创建并完成引导') }}
    </n-button>
  </div>
</template>

<script setup lang="ts">
import { t } from '@/composables/i18n';
import type { SetupPlatformAdminForm } from './types';

const model = defineModel<SetupPlatformAdminForm>({ required: true });
defineProps<{ submitting?: boolean }>();
defineEmits<{ submit: [] }>();
</script>

<style scoped>
.step-content { display: grid; gap: 4px; }
.step-heading { margin-bottom: 14px; }
.step-kicker { color: #3568e8; font-size: 12px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }
.section-heading { display: flex; align-items: flex-start; gap: 12px; margin-top: 8px; }
.section-heading-icon { display: grid; width: 38px; height: 38px; flex: 0 0 38px; place-items: center; border-radius: 11px; background: #eaf0ff; color: #315fc8; }
.section-heading-icon svg { width: 20px; fill: none; stroke: currentColor; stroke-linecap: round; stroke-linejoin: round; stroke-width: 1.8; }
.section-heading h2 { margin: 0 0 4px; color: #10204a; font-size: 24px; line-height: 1.35; }
.section-heading p { margin: 0; color: #64748b; font-size: 13px; line-height: 1.6; }
</style>
