<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { NEmpty, NSpin, useMessage } from 'naive-ui'
import { fetchShortcutPlan, type ShortcutPlan } from '@/api/shortcut-settings'
import { t } from '@/composables/i18n'
import adminProductUiExtension from '@movo-admin-product-extension'

const props = defineProps<{ onEditDefault?: () => void }>()
const message = useMessage()
const loading = ref(false)
const plan = ref<ShortcutPlan | null>(null)
const EnterpriseShortcutSettings = adminProductUiExtension.shortcutSettingsExtension

onMounted(async () => {
  loading.value = true
  try { plan.value = await fetchShortcutPlan() }
  catch { message.error(t('快捷入口方案加载失败')) }
  finally { loading.value = false }
})
</script>

<template>
  <div class="shortcut-overview">
    <div class="settings-header">
      <div>
        <div class="settings-title">{{ t('快捷入口方案') }}</div>
        <div class="settings-subtitle">{{ t('按方案管理不同员工看到的快捷入口。') }}</div>
      </div>
    </div>
    <n-spin :show="loading">
      <article v-if="plan" class="default-scheme-card">
        <div>
          <strong>{{ plan.name }}</strong>
          <span>{{ t('所有员工未命中其他方案时使用') }} · {{ t('当前展示 {count} 个入口', { count: plan.entries.filter(item => item.enabled).length }) }}</span>
        </div>
        <n-button secondary @click="props.onEditDefault?.()">{{ t('维护默认入口') }}</n-button>
      </article>
      <n-empty v-else :description="t('暂无默认方案')" />
    </n-spin>
    <component :is="EnterpriseShortcutSettings" v-if="EnterpriseShortcutSettings" />
  </div>
</template>

<style scoped>
.shortcut-overview { display: grid; gap: 16px; }
.settings-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.settings-title { color: #182236; font-size: 20px; font-weight: 700; }
.settings-subtitle { margin-top: 6px; color: #7b8799; font-size: 13px; }
.default-scheme-card { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 18px; border: 1px solid #e5eaf2; border-radius: 14px; background: #fff; }
.default-scheme-card div { display: grid; gap: 5px; min-width: 0; }
.default-scheme-card strong { color: #26344a; font-size: 15px; }
.default-scheme-card span { color: #8a96a8; font-size: 12px; }
</style>
