<template>
  <n-modal :show="show" preset="card" :title="t('dshPlugins.add')" style="width:min(560px,92vw)" @update:show="emit('update:show', $event)">
    <div class="source-tabs">
      <n-button :type="mode === 'remote' ? 'primary' : 'default'" @click="mode = 'remote'">{{ t('dshPlugins.remote') }}</n-button>
      <n-button :type="mode === 'local' ? 'primary' : 'default'" @click="mode = 'local'">{{ t('dshPlugins.local') }}</n-button>
    </div>
    <template v-if="mode === 'remote'">
      <n-form-item :label="t('dshPlugins.spec')"><n-input v-model:value="spec" placeholder="@scope/plugin@1.2.3" @keyup.enter="submit" /></n-form-item>
      <p class="help">{{ t('dshPlugins.specHelp') }}</p>
    </template>
    <template v-else>
      <n-form-item :label="t('dshPlugins.archive')"><input class="file-input" type="file" accept=".tgz,.gz,application/gzip" @change="selectFile" /></n-form-item>
      <p class="help">{{ t('dshPlugins.archiveHelp') }}</p>
    </template>
    <p class="help">{{ t('dshPlugins.uiLimit') }}</p>
    <p v-if="installing" class="help" role="status">{{ t('dshPlugins.environmentPreparing') }}</p>
    <template #footer><n-space justify="end"><n-button @click="emit('update:show', false)">{{ t('dshPlugins.cancel') }}</n-button><n-button type="primary" :loading="installing" :disabled="mode === 'remote' ? !spec.trim() : !file" @click="submit">{{ t('dshPlugins.install') }}</n-button></n-space></template>
  </n-modal>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { NButton, NFormItem, NInput, NModal, NSpace } from 'naive-ui'
import { t } from '@/composables/i18n'

const props = defineProps<{ show: boolean; installing: boolean }>()
const emit = defineEmits<{ 'update:show': [value: boolean]; install: [source: string | File] }>()
const mode = ref<'remote' | 'local'>('remote')
const spec = ref('')
const file = ref<File | null>(null)
watch(() => props.show, visible => { if (!visible) { spec.value = ''; file.value = null; mode.value = 'remote' } })
function selectFile(event: Event) { file.value = (event.target as HTMLInputElement).files?.[0] || null }
function submit() {
  if (props.installing) return
  if (mode.value === 'local' && file.value) emit('install', file.value)
  if (mode.value === 'remote' && spec.value.trim()) emit('install', spec.value.trim())
}
</script>

<style scoped>.source-tabs{display:flex;gap:8px;margin-bottom:18px}.file-input{width:100%;padding:8px;border:1px solid #d9e0ec;border-radius:8px}.help{margin:0;color:#8490a2;font-size:13px;line-height:1.6}</style>
