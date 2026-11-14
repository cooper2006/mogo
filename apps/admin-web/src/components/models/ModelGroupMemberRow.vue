<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useMessage } from 'naive-ui';
import { t } from '@/composables/i18n';
import { createModelInstance, deleteModelInstance, discoverProviderModels, updateModelInstance, type DiscoveredModel, type ImageModelSettings, type ImageRuntimeKind, type ModelGroupItem, type ModelInstanceItem, type ModelInstancePayload, type ModelProviderItem, type ModelStatus, type ModelPricing } from '@/api/models';
import adminProductUiExtension from '@mogo-admin-product-extension';
import ImageModelRuntimeFields from './ImageModelRuntimeFields.vue';
import ModelPricingFields from './ModelPricingFields.vue';
import ModelAccessExtensionPanel from './ModelAccessExtensionPanel.vue';
import { capabilityLabel } from './capabilityLabels';
import { modelApiErrorText } from './modelApiError';
import CubeOutline from '@vicons/ionicons5/es/CubeOutline';
import PlayOutline from '@vicons/ionicons5/es/PlayOutline';
import ChevronDownOutline from '@vicons/ionicons5/es/ChevronDownOutline';
import ChevronUpOutline from '@vicons/ionicons5/es/ChevronUpOutline';
import SaveOutline from '@vicons/ionicons5/es/SaveOutline';
import TrashOutline from '@vicons/ionicons5/es/TrashOutline';

const props = defineProps<{ group: ModelGroupItem; provider?: ModelProviderItem; model?: ModelInstanceItem; expanded?: boolean }>();
const emit = defineEmits<{ (event: 'saved', model: ModelInstanceItem): void; (event: 'deleted', id: string): void; (event: 'cancel'): void; (event: 'select', id: string): void }>();
const message = useMessage();
const extension = adminProductUiExtension.modelAccess;
const open = ref(Boolean(props.expanded || !props.model));
const saving = ref(false);
const accessLoading = ref(false);
const access = ref<unknown>(extension?.createValue(true));
const pickerVisible = ref(false);
const discoveredModels = ref<DiscoveredModel[]>([]);
const pickedModelIds = ref<string[]>([]);
const discoverLoading = ref(false);
const bulkSaving = ref(false);
const form = ref({ displayName: '', modelName: '', capabilities: ['chat'] as string[], status: 'active' as ModelStatus, runtimeKind: '' as ImageRuntimeKind | '', imageSettings: {} as ImageModelSettings, pricing: null as ModelPricing | null });
const imageModel = computed(() => form.value.capabilities.includes('image_generation'));
const selectable = computed(() => form.value.capabilities.some((item) => ['chat', 'text', 'image_generation'].includes(item)));
const capabilityOptions = computed(() => ['chat', 'vision', 'embedding', 'rerank', 'image_generation'].map((value) => ({ label: capabilityLabel(value), value })));
const runtimeDefault = computed<ImageRuntimeKind>(() => props.provider?.providerType === 'azure_openai' ? 'azure_openai_images' : 'openai_images');

watch(() => props.model?.id, async () => {
  const model = props.model;
  form.value = model
    ? { displayName: model.displayName, modelName: model.modelName, capabilities: [...model.capabilities], status: model.status, runtimeKind: model.runtimeKind || runtimeDefault.value, imageSettings: { ...model.imageSettings }, pricing: model.pricing ? { ...model.pricing } : null }
    : { displayName: '', modelName: '', capabilities: ['chat'], status: 'active', runtimeKind: runtimeDefault.value, imageSettings: {}, pricing: null };
  access.value = extension?.createValue(true);
  if (model && extension && model.capabilities.some((item) => ['chat', 'text', 'image_generation'].includes(item))) {
    accessLoading.value = true;
    try { access.value = await extension.load(model.id); }
    catch (error) { message.error(modelApiErrorText(error)); }
    finally { accessLoading.value = false; }
  }
}, { immediate: true });
watch(() => props.expanded, (value) => { if (value) open.value = true; });
watch(() => props.model?.capabilities, (capabilities) => {
  if (capabilities?.includes('vision') && !form.value.capabilities.includes('vision')) {
    form.value.capabilities = [...form.value.capabilities, 'vision'];
  }
});

function imageSettingsAreValid(): boolean {
  if (!imageModel.value || form.value.runtimeKind !== 'custom_images') return true;
  try {
    const parsed = JSON.parse(String(form.value.imageSettings.extraParamsJson || '{}').trim() || '{}');
    return Boolean(parsed) && !Array.isArray(parsed) && typeof parsed === 'object';
  } catch { return false; }
}

function buildPayload(): ModelInstancePayload {
  const modelName = form.value.modelName.trim();
  return {
    providerId: props.group.providerId, groupId: props.group.id, orgId: props.model?.orgId || '',
    displayName: form.value.displayName.trim() || modelName, modelName,
    baseUrl: props.group.baseUrl, apiVersion: props.group.apiVersion, apiKey: '',
    capabilities: [...form.value.capabilities],
    runtimeKind: imageModel.value ? form.value.runtimeKind : '', imageSettings: imageModel.value ? { ...form.value.imageSettings } : {},
    maxContextTokens: props.model?.maxContextTokens || 0, status: form.value.status,
    isDefault: props.model?.isDefault || false, priority: props.model?.priority || 100,
    pricing: form.value.pricing,
  };
}

async function saveAccess(saved: ModelInstanceItem): Promise<boolean> {
  if (!selectable.value || !extension) return true;
  try { await extension.save(saved.id, access.value); return true; }
  catch (error) { message.error(`${t('modelGroup.memberSavedAccessFailed')}: ${modelApiErrorText(error)}`); return false; }
}

async function save() {
  const warning = selectable.value ? extension?.validate?.(access.value) : null;
  if (warning) { message.warning(t(warning)); return; }
  if (!form.value.modelName.trim() || !form.value.capabilities.length) { message.warning(t('modelGroup.memberRequired')); return; }
  if (!imageSettingsAreValid()) { message.warning(t('legacy.enter_a_valid_json_object')); return; }
  saving.value = true;
  try {
    const payload = buildPayload();
    const saved = props.model ? await updateModelInstance(props.model.id, payload) : await createModelInstance(payload);
    const accessSaved = await saveAccess(saved);
    emit('saved', saved);
    if (!accessSaved) return;
    message.success(t('modelGroup.memberSaved'));
  } catch (error) { message.error(modelApiErrorText(error)); }
  finally { saving.value = false; }
}

async function remove() {
  if (!props.model || !window.confirm(t('modelGroup.deleteMemberConfirm', { name: props.model.displayName }))) return;
  saving.value = true;
  try { await deleteModelInstance(props.model.id); emit('deleted', props.model.id); }
  catch (error) { message.error(modelApiErrorText(error)); }
  finally { saving.value = false; }
}

/** 组内实例自己没有 Base URL / Key，用模型组的共享凭据拉上游模型列表。 */
async function openModelPicker() {
  if (!props.group.baseUrl.trim()) {
    message.warning(t('请先保存模型组的 Base URL'));
    return;
  }
  discoverLoading.value = true;
  pickerVisible.value = true;
  pickedModelIds.value = [];
  try {
    discoveredModels.value = await discoverProviderModels({
      providerType: props.provider?.providerType || 'openai_compatible',
      baseUrl: props.group.baseUrl,
      apiVersion: props.group.apiVersion,
      apiKey: '',
      groupId: props.group.id,
    });
    if (!discoveredModels.value.length) message.warning(t('未获取到模型列表，请检查模型组连接配置'));
  } catch (error) {
    message.error(modelApiErrorText(error));
  } finally {
    discoverLoading.value = false;
  }
}

function togglePickModel(id: string) {
  const idx = pickedModelIds.value.indexOf(id);
  if (idx >= 0) pickedModelIds.value.splice(idx, 1);
  else pickedModelIds.value.push(id);
}

/** 确定：单选填入表单；新增态多选批量建组内成员；编辑态多选只替换当前模型 ID。 */
async function confirmPickModels() {
  const picked = pickedModelIds.value;
  if (!picked.length) {
    message.warning(t('请先选择模型'));
    return;
  }
  if (picked.length === 1) {
    form.value.modelName = picked[0];
    pickerVisible.value = false;
    return;
  }
  // 编辑已有成员时不能批量创建：组内实例没有独立凭据，逐个 POST 会全部失败。
  if (props.model) {
    form.value.modelName = picked[0];
    pickerVisible.value = false;
    message.warning(t('编辑已有模型时只能替换为单个模型，已填入 {name}；如需新增多个模型请点「添加模型」逐个添加', { name: picked[0] }));
    return;
  }
  bulkSaving.value = true;
  const baseDisplay = form.value.displayName.trim();
  try {
    let created = 0;
    let lastSaved: ModelInstanceItem | null = null;
    const failures: string[] = [];
    for (const modelId of picked) {
      const payload = buildPayload();
      payload.modelName = modelId;
      payload.displayName = baseDisplay ? `${baseDisplay} · ${modelId}` : modelId;
      try {
        const saved = await createModelInstance(payload);
        await saveAccess(saved);
        lastSaved = saved;
        created += 1;
      } catch (error) {
        failures.push(`${modelId}: ${modelApiErrorText(error)}`);
      }
    }
    // 只通知一次：父组件刷新列表并关闭草稿行，已创建的所有成员都会出现
    if (created && lastSaved) emit('saved', lastSaved);
    if (created === picked.length) {
      message.success(t('已批量创建 {n} 个模型', { n: created }));
    } else if (created > 0) {
      message.warning(t('批量创建完成：成功 {ok} 个，失败 {fail} 个', { ok: created, fail: failures.length }));
    } else {
      message.error(t('批量创建失败：{msg}', { msg: failures[0] || '未知错误' }));
    }
  } finally {
    bulkSaving.value = false;
    pickerVisible.value = false;
    pickedModelIds.value = [];
  }
}
</script>

<template>
  <section class="member-row">
    <div class="member-head">
      <button type="button" class="member-toggle" @click="open = !open">
        <n-icon size="19" class="member-icon"><CubeOutline /></n-icon>
        <span><strong>{{ model?.displayName || t('modelGroup.newMember') }}</strong><small>{{ model?.modelName || t('modelGroup.unsaved') }}</small></span>
      </button>
      <n-button v-if="model" size="small" quaternary @click="emit('select', model.id)"><template #icon><n-icon><PlayOutline /></n-icon></template>{{ t('modelGroup.testThisModel') }}</n-button>
      <n-button size="small" quaternary @click="open = !open"><template #icon><n-icon><ChevronUpOutline v-if="open" /><ChevronDownOutline v-else /></n-icon></template>{{ open ? t('modelGroup.collapse') : t('modelGroup.expand') }}</n-button>
    </div>
    <div v-if="open" class="member-fields">
      <n-form label-placement="top">
        <div class="field-grid">
          <n-form-item :label="t('legacy.model_id')">
            <div class="model-id-field">
              <n-input v-model:value="form.modelName" :placeholder="t('modelGroup.modelIdPlaceholder')" />
              <n-button :loading="discoverLoading" @click="openModelPicker">{{ t('获取列表') }}</n-button>
            </div>
          </n-form-item>
          <n-form-item :label="t('legacy.display_name')"><n-input v-model:value="form.displayName" :placeholder="t('modelGroup.nameDefaultsToId')" /></n-form-item>
          <n-form-item :label="t('legacy.capabilities')"><n-select v-model:value="form.capabilities" multiple :options="capabilityOptions" /></n-form-item>
          <n-form-item :label="t('legacy.status')"><n-select v-model:value="form.status" :options="[{ label: t('modelGroup.active'), value: 'active' }, { label: t('modelGroup.disabled'), value: 'disabled' }]" /></n-form-item>
        </div>
        <ModelPricingFields v-model="form.pricing" />
        <n-collapse v-if="imageModel"><n-collapse-item :title="t('modelGroup.imageSettings')" name="image"><ImageModelRuntimeFields v-model:runtimeKind="form.runtimeKind" v-model:imageSettings="form.imageSettings" :provider-type="provider?.providerType || ''" /></n-collapse-item></n-collapse>
        <n-collapse v-if="extension && selectable"><n-collapse-item :title="t('modelGroup.memberAccess')" name="access"><ModelAccessExtensionPanel v-model="access" :loading="accessLoading" grouped /></n-collapse-item></n-collapse>
      </n-form>
      <div class="member-actions">
        <n-button v-if="model" size="small" tertiary type="error" :disabled="saving" @click="remove"><template #icon><n-icon><TrashOutline /></n-icon></template>{{ t('legacy.delete_model') }}</n-button>
        <n-button v-else size="small" @click="emit('cancel')">{{ t('legacy.cancel') }}</n-button>
        <n-button size="small" type="primary" :loading="saving || accessLoading" @click="save"><template #icon><n-icon><SaveOutline /></n-icon></template>{{ t('modelGroup.saveMember') }}</n-button>
      </div>
    </div>
  </section>

  <n-modal v-model:show="pickerVisible" preset="card" :title="t('选择模型')" style="width: 640px">
    <n-spin :show="discoverLoading">
      <div v-if="discoveredModels.length" class="mg-picker-list">
        <button
          v-for="row in discoveredModels"
          :key="row.id"
          type="button"
          class="mg-picker-item"
          :class="{ 'is-selected': pickedModelIds.includes(row.id) }"
          @click="togglePickModel(row.id)"
        >
          <span class="mg-picker-check" aria-hidden="true">
            <svg viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M3.5 8.5L6.5 11.5L12.5 5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
          </span>
          <span class="mg-picker-id">{{ row.id }}</span>
          <span v-if="row.ownedBy" class="mg-picker-owner">{{ row.ownedBy }}</span>
        </button>
      </div>
      <n-empty v-else :description="discoverLoading ? t('正在获取模型列表...') : t('暂无可选项，请检查模型组连接配置')" />
    </n-spin>
    <template #footer>
      <n-space justify="end" align="center">
        <span class="mg-picker-hint">{{ pickedModelIds.length ? t('已选 {n} 个', { n: pickedModelIds.length }) : '' }}</span>
        <n-button @click="pickerVisible = false">{{ t('取消') }}</n-button>
        <n-button type="primary" :loading="bulkSaving" :disabled="!pickedModelIds.length" @click="confirmPickModels">{{ t('确定') }}</n-button>
      </n-space>
    </template>
  </n-modal>
</template>

<style scoped>
.member-row { border: 1px solid var(--mg-border); border-radius: 9px; background: var(--mg-bg-surface); }
.member-head, .member-actions { display: flex; align-items: center; gap: 8px; padding: 10px 12px; }
.member-toggle { display: flex; align-items: center; gap: 10px; flex: 1; min-width: 0; border: 0; background: none; text-align: left; cursor: pointer; }
.member-toggle > span { min-width: 0; }
.member-icon { flex: none; color: var(--mg-brand); }
.member-toggle strong, .member-toggle small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.member-toggle small { color: var(--mg-text-3); }
.member-fields { padding: 4px 14px 14px; border-top: 1px solid var(--mg-border-subtle); }
.field-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); column-gap: 12px; }
.member-actions { justify-content: flex-end; padding: 8px 0 0; }
.model-id-field { display: flex; gap: 8px; width: 100%; }
.model-id-field > :first-child { flex: 1; min-width: 0; }
.mg-picker-list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; max-height: 420px; overflow: auto; padding: 2px; }
.mg-picker-item { position: relative; display: flex; flex-direction: column; gap: 2px; padding: 10px 34px 10px 12px; border: 1px solid rgba(28, 45, 82, 0.12); border-radius: 8px; background: var(--mg-bg-surface); color: inherit; text-align: left; cursor: pointer; }
.mg-picker-item:hover { border-color: rgba(54, 106, 255, 0.4); background: var(--mg-bg-surface-hover); }
.mg-picker-item.is-selected { border-color: #366aff; background: rgba(54, 106, 255, 0.06); }
.mg-picker-check { position: absolute; top: 10px; right: 10px; width: 16px; height: 16px; display: grid; place-items: center; border: 1px solid rgba(28, 45, 82, 0.2); border-radius: 4px; color: #fff; opacity: 0; }
.mg-picker-item.is-selected .mg-picker-check { opacity: 1; background: #366aff; border-color: #366aff; }
.mg-picker-check svg { width: 14px; height: 14px; }
.mg-picker-id { font-size: 13px; font-weight: 600; word-break: break-all; }
.mg-picker-owner { font-size: 11px; color: var(--mg-text-3); }
.mg-picker-hint { font-size: 12px; color: var(--mg-text-3); margin-right: auto; }
@media (max-width: 720px) { .field-grid { grid-template-columns: 1fr; } .mg-picker-list { grid-template-columns: 1fr; } }
</style>
