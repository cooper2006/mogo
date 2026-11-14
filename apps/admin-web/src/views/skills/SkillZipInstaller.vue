<template>
  <n-modal :show="show" preset="card" :title="t('legacy.install_organization_skill_from_zip')" style="width: 620px" @update:show="emit('update:show', $event)">
    <div class="zip-dropzone" :class="{ dragging }" @dragenter.prevent="dragging = true" @dragover.prevent @dragleave.prevent="dragging = false" @drop.prevent="onDrop" @click="input?.click()">
      <input ref="input" hidden type="file" accept=".zip,application/zip" @change="onChoose" />
      <strong>{{ file?.name || t('legacy.drop_a_zip_here_or_click_to_choose_a') }}</strong>
      <span>{{ t('skills.install_limit') }}</span>
    </div>
    <n-alert v-if="result" class="install-result" type="success" :title="result.duplicate ? t('additional.this_version_is_already_installed') : t('additional.organization_skill_installed_successfully')">
      {{ result.name }} · {{ result.version }} · {{ t('skills.install_file_count', { count: result.fileCount }) }}
      <template v-if="result.childCount"> · {{ t('skills.install_child_count', { count: result.childCount }) }}</template>
      <div v-if="result.children.length" class="expert-children">
        <n-tag v-for="child in result.children" :key="child.slug" size="small" :bordered="false">{{ child.name }} · {{ child.version }}</n-tag>
      </div>
      <ul v-if="result.warnings.length"><li v-for="warning in result.warnings" :key="warning.code + (warning.tool || '')">{{ localizeSkillInstallWarning(warning) }}</li></ul>
    </n-alert>
    <n-alert v-if="dependencyMessage" class="install-result" :type="dependencyStatus === 'failed' ? 'error' : 'info'">{{ dependencyMessage }}</n-alert>
    <n-alert v-else-if="failure" class="install-result" type="error" :title="failureTitle || t('legacy.skill_installation_failed')">{{ failure }}</n-alert>
    <n-alert v-if="upgrade" class="install-result" type="warning" :title="t('additional.confirm_skill_update')">
      {{ t('additional.installed_version') }} {{ upgrade.currentVersion || '-' }} → {{ t('additional.new_version') }} {{ upgrade.incomingVersion || '-' }}
    </n-alert>
    <template #footer>
      <n-space justify="end">
        <n-button v-if="!result" @click="close">{{ t('legacy.cancel') }}</n-button>
        <n-button v-if="result" type="primary" @click="close">{{ t('legacy.close') }}</n-button>
        <n-button v-else type="primary" :disabled="!file" :loading="installing" @click="install(Boolean(upgrade))">{{ upgrade ? t('additional.confirm_update') : t('additional.install_skill') }}</n-button>
      </n-space>
    </template>
  </n-modal>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { NAlert, NButton, NModal, NSpace, NTag } from 'naive-ui';
import { fetchSkillDependencyStatus, installSkillZip, type SkillInstallResult } from '@/api/skills';
import { t } from '@/composables/i18n';
import { localizeSkillInstallError, localizeSkillInstallWarning } from './skillInstallError';

const props = defineProps<{ show: boolean }>();
const emit = defineEmits<{ 'update:show': [value: boolean]; installed: [result: SkillInstallResult] }>();
const input = ref<HTMLInputElement | null>(null);
const file = ref<File | null>(null);
const dragging = ref(false);
const installing = ref(false);
const result = ref<SkillInstallResult | null>(null);
const failure = ref('');
const failureTitle = ref('');
const upgrade = ref<NonNullable<SkillInstallResult['upgrade']> | null>(null);
const dependencyStatus = ref('');
const dependencyMessage = computed(() => {
  const key = dependencyStatus.value;
  return ['preparing', 'ready', 'failed', 'unavailable', 'disabled'].includes(key) ? t(`skillDeps.${key}` as 'skillDeps.preparing') : '';
});
let pollTimer: ReturnType<typeof setTimeout> | null = null;
function stopPolling() { if (pollTimer) clearTimeout(pollTimer); pollTimer = null; }
async function pollDependencies() {
  if (!props.show || !result.value) return;
  try { dependencyStatus.value = (await fetchSkillDependencyStatus(result.value.id)).status; }
  catch { dependencyStatus.value = 'unavailable'; }
  if (['preparing', 'not_started', 'unavailable'].includes(dependencyStatus.value)) pollTimer = setTimeout(pollDependencies, 3000);
}
function startPolling() {
  stopPolling();
  dependencyStatus.value = result.value?.dependencyPreparation || '';
  if (['preparing', 'not_started', 'unavailable'].includes(dependencyStatus.value)) pollTimer = setTimeout(pollDependencies, 3000);
}
function close() { emit('update:show', false); }
function select(candidate?: File) { if (!candidate) return; stopPolling(); dependencyStatus.value = ''; if (!candidate.name.toLowerCase().endsWith('.zip')) { file.value = null; result.value = null; failureTitle.value = t('legacy.skill_package_validation_failed'); failure.value = t('additional.select_a_skill_package_in_zip_format'); return; } file.value = candidate; result.value = null; upgrade.value = null; failure.value = ''; failureTitle.value = ''; }
function onChoose(event: Event) { const target = event.target as HTMLInputElement; select(target.files?.[0]); target.value = ''; }
function onDrop(event: DragEvent) { dragging.value = false; select(event.dataTransfer?.files?.[0]); }
async function install(confirmReplace = false) { if (!file.value) return; installing.value = true; failure.value = ''; failureTitle.value = ''; try { result.value = await installSkillZip(file.value, confirmReplace); upgrade.value = null; startPolling(); emit('installed', result.value); } catch (error: any) { const detail = error?.response?.data?.detail; if (detail?.code === 'skill_upgrade_confirmation_required' && detail.upgrade) { upgrade.value = detail.upgrade; return; } const localized = localizeSkillInstallError(error); failureTitle.value = localized.title; failure.value = localized.message; } finally { installing.value = false; } }
watch(() => props.show, visible => { if (!visible) { stopPolling(); dependencyStatus.value = ''; file.value = null; result.value = null; upgrade.value = null; failure.value = ''; failureTitle.value = ''; } });
onBeforeUnmount(stopPolling);
defineExpose({ select });
</script>

<style scoped>
.zip-dropzone { min-height: 180px; border: 2px dashed var(--mg-border); border-radius: 12px; background: var(--mg-bg-surface); display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 10px; cursor: pointer; color: var(--mg-text-2); }
.zip-dropzone.dragging { border-color: var(--mg-brand); background: var(--mg-brand-soft); }
.zip-dropzone strong { color: var(--mg-text-1); font-size: 16px; }
.zip-dropzone span { font-size: 12px; }
.install-result { margin-top: 16px; }
.expert-children { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
</style>
