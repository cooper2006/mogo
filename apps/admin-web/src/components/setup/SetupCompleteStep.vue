<template>
  <div class="complete-content">
    <n-alert type="success" :show-icon="true" :title="t('平台超级管理员已创建')">
      {{ t('引导已完成。请使用平台超级管理员登录平台控制台，然后创建第一个租户。') }}
    </n-alert>

    <div class="next-steps">
      <div class="next-step">
        <span class="next-step-index">1</span>
        <div class="next-step-copy">
          <strong>{{ t('登录平台控制台') }}</strong>
          <span v-if="platformAdminUsername">{{ t('使用账号 {username} 登录。', { username: platformAdminUsername }) }}</span>
          <span v-else>{{ t('使用平台超级管理员账号登录。') }}</span>
        </div>
      </div>
      <div class="next-step">
        <span class="next-step-index">2</span>
        <div class="next-step-copy">
          <strong>{{ t('去创建第一个租户') }}</strong>
          <span>{{ t('在“租户管理”中填写企业名称与管理员账号即可开通一个企业。') }}</span>
        </div>
      </div>
    </div>

    <div class="complete-actions">
      <n-button size="large" secondary @click="$emit('login')">{{ t('登录平台控制台') }}</n-button>
      <n-button type="primary" size="large" @click="$emit('createTenant')">{{ t('去创建第一个租户') }}</n-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { t } from '@/composables/i18n';

defineProps<{
  platformAdminUsername: string;
}>();
defineEmits<{ login: []; createTenant: [] }>();
</script>

<style scoped>
.complete-content { display: grid; gap: 20px; }
.next-steps { display: grid; gap: 12px; }
.next-step { display: flex; align-items: flex-start; gap: 12px; padding: 12px 14px; border: 1px solid #e2e8f0; border-radius: 12px; background: #f8fafc; }
.next-step-index { display: grid; width: 26px; height: 26px; flex: 0 0 26px; place-items: center; border-radius: 50%; background: #3568e8; color: #fff; font-size: 13px; font-weight: 700; }
.next-step-copy { display: grid; gap: 3px; }
.next-step-copy strong { color: #10204a; font-size: 14px; }
.next-step-copy span { color: #64748b; font-size: 13px; line-height: 1.6; }
.complete-actions { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
@media (max-width: 600px) { .complete-actions { grid-template-columns: 1fr; } }
</style>
