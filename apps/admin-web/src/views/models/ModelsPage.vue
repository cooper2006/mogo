<template>
  <div class="page-stack model-page">

    <div class="metrics-row">
      <n-card v-for="item in metricCards" :key="item.key" class="metric-card" :bordered="false" size="small">
        <div class="metric-main">
          <span class="metric-icon" :class="`metric-icon-${item.key}`" v-html="item.icon"></span>
          <div class="metric-body">
            <div class="metric-label">{{ item.label }}</div>
            <div class="metric-value">{{ item.value }}</div>
          </div>
        </div>
        <div class="metric-note">{{ item.note }}</div>
      </n-card>
    </div>

    <n-card class="list-card shell-card" :bordered="false" size="large">
      <n-alert
        v-if="orgQuota === 0 && instances.length > 0"
        type="warning"
        closable
        class="quota-warning-alert"
        :title="t('企业额度警示')"
        style="margin-bottom: 16px;"
      >
        {{ t('当前企业本周期总额度为 0，所有模型将无法被调用。请先前往') }}
        <router-link to="/organizations/traffic?open=quota" class="alert-link" style="color: #2563eb; font-weight: 600; text-decoration: underline;">
          {{ t('流量分配') }}
        </router-link>
        {{ t('配置企业总额度与成员额度。') }}
      </n-alert>

      <div class="list-filter-row">

          <n-space align="center" :size="10" class="filter-left">
            <n-input v-model:value="filters.keyword" :placeholder="t('搜索名称 / 模型 ID / Base URL')" clearable class="keyword-input" />
            <n-select
              v-model:value="filters.providerId"
              :options="providerOptions"
              :placeholder="t('供应商')"
              clearable
              style="width: 160px"
            />
            <n-select
              v-model:value="filters.status"
              :options="statusOptions"
              :placeholder="t('状态')"
              clearable
              style="width: 120px"
            />
          </n-space>
        <n-space :size="10" class="filter-right">
            <n-button secondary @click="reload">
              <template #icon>
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
                  <path d="M3 3v5h5" />
                  <path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16" />
                  <path d="M16 16h5v5" />
                </svg>
              </template>
              {{ t('刷新') }}
            </n-button>
            <n-button secondary @click="openGroupCreate">{{ t('modelGroup.create') }}</n-button>
            <n-button type="primary" strong @click="openCreate">
              <template #icon>
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M5 12h14" />
                  <path d="M12 5v14" />
                </svg>
              </template>
              {{ t('新增模型') }}
            </n-button>
        </n-space>
      </div>

      <div class="list-body">
        <n-spin :show="loading">
          <div v-if="filteredInstances.length || filteredGroups.length" class="model-grid">
            <ModelGroupCard
              v-for="group in filteredGroups"
              :key="group.id"
              :group="group"
              :models="instances.filter((item) => item.groupId === group.id)"
              :providers="providers"
              @edit="openGroupEdit(group)"
              @add="openGroupEdit(group)"
              @edit-model="openGroupModelEdit"
            />
            <button
              v-for="model in filteredStandaloneInstances"
              :key="model.id"
              class="model-config-card"
              type="button"
              @click="openEdit(model)"
            >
              <div class="card-head">
                <span class="provider-badge">{{ providerLabel({ code: model.providerCode, name: model.providerName, providerType: model.providerType }) }}</span>
                <n-space :size="6" class="state-tags">
                  <n-tag :type="model.status === 'active' ? 'success' : 'default'" size="small" :bordered="false">
                    {{ model.status === 'active' ? t('启用') : t('禁用') }}
                  </n-tag>
                </n-space>
              </div>

              <div class="card-body">
                <div class="card-title">{{ model.displayName }}</div>
                <div class="card-model-id">{{ model.modelName }}</div>
              </div>

              <div class="capability-row">
                <n-tag
                  v-for="item in model.capabilities"
                  :key="item"
                  size="small"
                  :bordered="false"
                  class="capability-tag"
                >
                  {{ capabilityLabel(item) }}
                </n-tag>
              </div>

              <div class="card-footnote">
                {{ t('最近更新：') }}{{ formatAdminDateTime(model.updatedAt, t('未知')) }}
              </div>

              <div class="card-bottom">
                <div class="card-actions">
                  <n-button size="small" tertiary @click.stop="runTest(model)">{{ t('测试') }}</n-button>
                  <n-button size="small" tertiary type="error" @click.stop="confirmDelete(model)">{{ t('删除') }}</n-button>
                </div>
              </div>
            </button>

            <button class="model-config-card add-model-card" type="button" @click="openCreate">
              <div class="add-symbol">+</div>
              <div class="add-title">{{ t('新增模型') }}</div>
              <div class="add-copy">{{ t('配置 OpenAI、Azure OpenAI、通义千问、DeepSeek 或自定义兼容接口。') }}</div>
            </button>
          </div>

          <n-empty v-else :description="t('暂无模型配置')">
            <template #extra>
              <n-button type="primary" @click="openCreate">{{ t('新增第一个模型') }}</n-button>
            </template>
          </n-empty>
        </n-spin>
      </div>
    </n-card>

    <ModelGroupEditor
      v-model:show="groupEditorVisible"
      :group="editingGroup"
      :providers="providers"
      :models="instances"
      :selected-model-id="selectedGroupModelId"
      @saved="onGroupSaved"
      @deleted="reload"
      @member-changed="reload"
    />
  </div>

  <n-modal v-model:show="editorVisible" preset="card" :title="editorTitle" style="width: 980px">
    <div class="editor-layout" :class="{ 'single-column': editorMode === 'create' }">
      <n-form class="editor-form" :model="form" label-placement="left" label-width="96">
        <n-grid :cols="2" :x-gap="14">
          <n-grid-item>
            <n-form-item :label="t('供应商')">
              <n-select
                v-model:value="form.providerId"
                :options="providerOptions"
                :placeholder="t('选择供应商')"
              />
            </n-form-item>
          </n-grid-item>
          <n-grid-item>
            <n-form-item :label="t('显示名称')">
              <n-input v-model:value="form.displayName" :placeholder="t('如: OpenAI 主模型')" />
            </n-form-item>
          </n-grid-item>
          <n-grid-item>
            <n-form-item :label="modelFieldLabel">
              <n-input-group>
                <n-input v-model:value="form.modelName" :placeholder="modelFieldPlaceholder" />
                <n-button :loading="discoverLoading" @click="openModelPicker">{{ t('获取列表') }}</n-button>
              </n-input-group>
            </n-form-item>
          </n-grid-item>
          <n-grid-item>
            <n-form-item :label="t('状态')">
              <n-select v-model:value="form.status" :options="statusOptions" />
            </n-form-item>
          </n-grid-item>
          <n-grid-item :span="2">
            <n-form-item label="Base URL">
              <n-input v-model:value="form.baseUrl" :placeholder="baseUrlPlaceholder" />
            </n-form-item>
          </n-grid-item>
          <n-grid-item v-if="isAzureProvider">
            <n-form-item label="API Version">
              <n-input v-model:value="form.apiVersion" placeholder="如: 2024-10-21" />
            </n-form-item>
          </n-grid-item>
          <n-grid-item>
            <n-form-item label="API Key">
              <n-input
                v-model:value="form.apiKey"
                type="password"
                show-password-on="click"
                :placeholder="apiKeyPlaceholder"
              />
            </n-form-item>
          </n-grid-item>
          <n-grid-item>
            <n-form-item :label="t('能力')">
              <n-select v-model:value="form.capabilities" multiple :options="capabilityOptions" />
            </n-form-item>
          </n-grid-item>
          <n-grid-item v-if="hasImageCapability" :span="2">
            <ImageModelRuntimeFields
              v-model:runtimeKind="form.runtimeKind"
              v-model:imageSettings="form.imageSettings"
              :provider-type="currentProvider?.providerType || ''"
            />
          </n-grid-item>
        </n-grid>
      </n-form>

      <aside v-if="editorMode === 'edit'" class="test-panel">
        <div class="test-title">{{ t('配置测试') }}</div>
        <div class="test-summary">
          <div>
            <span>{{ t('供应商') }}</span>
            <strong>{{ providerLabel(currentProvider) }}</strong>
          </div>
          <div>
            <span>{{ t('模型 ID') }}</span>
            <strong>{{ form.modelName || t('未填写') }}</strong>
          </div>
          <div>
            <span>Base URL</span>
            <strong>{{ form.baseUrl || currentProvider?.defaultBaseUrl || t('未设置') }}</strong>
          </div>
          <div v-if="isAzureProvider">
            <span>API Version</span>
            <strong>{{ form.apiVersion || t('未填写（默认 2024-10-21）') }}</strong>
          </div>
          <div>
            <span>{{ t('Key 状态') }}</span>
            <strong>{{ keyStateText }}</strong>
          </div>
        </div>

        <n-input
          v-model:value="testPrompt"
          type="textarea"
          :rows="4"
          :placeholder="t('测试提示词，后续接入 runtime 后用于发起一次轻量调用')"
        />
        <n-button block type="primary" secondary :loading="testing" :disabled="!form.id" @click="runEditorTest">
          {{ t('测试当前配置') }}
        </n-button>
        <div class="test-result" :class="{ success: testResultType === 'success', failed: testResultType === 'failed' }">
          {{ testResultText }}
        </div>
        <img
          v-if="testImageUrl"
          class="test-image-preview"
          :src="testImageUrl"
          :alt="t('图片模型测试结果')"
        />
      </aside>
    </div>

    <template #footer>
      <n-space justify="space-between" align="center">
        <n-button v-if="editorMode === 'edit'" tertiary type="error" @click="confirmDeleteFromEditor">{{ t('删除模型') }}</n-button>
        <span v-else />
        <n-space>
          <n-button @click="editorVisible = false">{{ t('取消') }}</n-button>
          <n-button type="primary" :loading="saving" @click="saveModel">{{ t('保存') }}</n-button>
        </n-space>
      </n-space>
    </template>
  </n-modal>

  <n-modal v-model:show="modelPickerVisible" preset="card" :title="t('选择模型')" style="width: 640px">
    <n-spin :show="discoverLoading">
      <div v-if="discoveredModels.length" class="model-picker-list">
        <button
          v-for="row in discoveredModels"
          :key="row.id"
          class="model-picker-item"
          :class="{ 'is-selected': pickedModelIds.includes(row.id) }"
          type="button"
          @click="togglePickModel(row.id)"
        >
          <span class="mp-check" aria-hidden="true">
            <svg viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M3.5 8.5L6.5 11.5L12.5 5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
          </span>
          <span class="mp-id">{{ row.id }}</span>
          <span v-if="row.ownedBy" class="mp-owner">{{ row.ownedBy }}</span>
        </button>
      </div>
      <n-empty
        v-else
        :description="discoverLoading ? t('正在获取模型列表...') : t('暂无可选项，请检查 Base URL 与 API Key 是否正确')"
      />
    </n-spin>
    <template #footer>
      <n-space justify="end">
        <span class="mp-footer-hint">{{ pickedModelIds.length ? t('已选 {n} 个', { n: pickedModelIds.length }) : '' }}</span>
        <n-button @click="modelPickerVisible = false">{{ t('取消') }}</n-button>
        <n-button type="primary" :loading="bulkSaving" :disabled="!pickedModelIds.length" @click="confirmPickModels">
          {{ t('确定') }}
        </n-button>
      </n-space>
    </template>
  </n-modal>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import axios from 'axios';
import { NInputGroup, useDialog, useMessage } from 'naive-ui';
import PageIntro from '@/components/PageIntro.vue';
import { t } from '@/composables/i18n';
import { formatAdminDateTime } from '@/composables/adminTimezone';
import ImageModelRuntimeFields from '@/components/models/ImageModelRuntimeFields.vue';
import {
  createModelInstance,
  deleteModelInstance,
  discoverProviderModels,
  fetchModelInstances,
  fetchModelProviders,
  fetchModelGroups,
  streamModelInstanceTest,
  testImageModelInstance,
  updateModelInstance,
  type DiscoveredModel,
  type ModelGroupItem,
  type ModelInstanceItem,
  type ModelInstancePayload,
  type ModelProviderItem,
  type ModelStatus,
  type ImageModelSettings,
  type ImageRuntimeKind,
} from '@/api/models';
import { fetchTrafficAllocationOverview } from '@/api/traffic-allocations';
import { capabilityLabel } from '@/components/models/capabilityLabels';
import { providerLabel } from '@/components/models/providerLabels';
import ModelGroupCard from '@/components/models/ModelGroupCard.vue';
import ModelGroupEditor from '@/components/models/ModelGroupEditor.vue';


interface ModelForm extends ModelInstancePayload {
  id: string;
  apiKeyMasked: string;
  runtimeKind: ImageRuntimeKind | '';
  imageSettings: ImageModelSettings;
}

const loading = ref(false);
const saving = ref(false);
const testing = ref(false);
const message = useMessage();
const dialog = useDialog();
const router = useRouter();
const providers = ref<ModelProviderItem[]>([]);
const instances = ref<ModelInstanceItem[]>([]);
const groups = ref<ModelGroupItem[]>([]);
const groupEditorVisible = ref(false);
const editingGroup = ref<ModelGroupItem | null>(null);
const selectedGroupModelId = ref('');
const editorVisible = ref(false);
const editorMode = ref<'create' | 'edit'>('create');
const suppressProviderChange = ref(false);
const testPrompt = ref(t('测试模型默认提示'));
const testResultText = ref(t('测试模型未保存'));
const testResultType = ref<'idle' | 'success' | 'failed'>('idle');
const testImageUrl = ref('');

const discoverLoading = ref(false);
const discoveredModels = ref<DiscoveredModel[]>([]);
const modelPickerVisible = ref(false);
/** 「选择模型」弹窗内勾选的模型 ID（支持多选） */
const pickedModelIds = ref<string[]>([]);
const bulkSaving = ref(false);

const filters = ref({
  keyword: '',
  providerId: null as string | null,
  status: null as ModelStatus | null,
});

const defaultForm = (): ModelForm => ({
  id: '',
  providerId: '',
  orgId: '',
  displayName: '',
  modelName: '',
  baseUrl: '',
  apiVersion: '',
  apiKey: '',
  apiKeyMasked: '',
  capabilities: ['chat'],
  runtimeKind: '',
  imageSettings: {},
  status: 'active',
  isDefault: false,
});

const form = ref<ModelForm>(defaultForm());
const orgQuota = ref<number | null>(null);


const statusOptions = computed(() => [
  { label: t('启用'), value: 'active' },
  { label: t('禁用'), value: 'disabled' },
]);

const capabilityOptions = computed(() => [
  { label: capabilityLabel('chat'), value: 'chat' },
  { label: capabilityLabel('vision'), value: 'vision' },
  { label: capabilityLabel('embedding'), value: 'embedding' },
  { label: capabilityLabel('rerank'), value: 'rerank' },
  { label: capabilityLabel('image_generation'), value: 'image_generation' },
]);

const providerOptions = computed(() =>
  providers.value
    .filter((item) => item.status === 'active')
    .map((item) => ({
      label: providerLabel(item),
      value: item.id,
    })),
);

const providerMap = computed(() => new Map(providers.value.map((item) => [item.id, item])));
const currentProvider = computed(() => providerMap.value.get(form.value.providerId));
const isAzureProvider = computed(() => currentProvider.value?.providerType === 'azure_openai');
const hasImageCapability = computed(() => form.value.capabilities.includes('image_generation'));
const editorTitle = computed(() => (editorMode.value === 'create' ? t('新增模型配置') : t('模型配置详情')));
const apiKeyPlaceholder = computed(() =>
  editorMode.value === 'create' ? t('请输入 API Key') : t('留空则保留当前 Key'),
);
const providerType = computed(() => currentProvider.value?.providerType || '');
const modelFieldLabel = computed(() => (isAzureProvider.value ? t('Deployment 名称') : t('模型 ID')));
const modelFieldPlaceholder = computed(() => {
  if (hasImageCapability.value) {
    return providerType.value === 'azure_openai'
      ? t('如: gpt-image-2-prod（Azure 部署名）')
      : t('如: qwen-image-plus / gpt-image-1');
  }
  switch (providerType.value) {
    case 'azure_openai':
      return t('如: gpt-4o-mini-prod（Azure 部署名）');
    case 'anthropic':
      return t('如: claude-3-5-sonnet-20241022');
    case 'gemini':
      return t('如: gemini-1.5-pro');
    case 'ollama':
      return t('如: llama3.1');
    default:
      return t('如: gpt-4.1 / qwen-plus / deepseek-chat');
  }
});
const baseUrlPlaceholder = computed(() => {
  switch (providerType.value) {
    case 'azure_openai':
      return 'https://YOUR-RESOURCE-NAME.openai.azure.com';
    case 'anthropic':
      return 'https://api.anthropic.com';
    case 'gemini':
      return 'https://generativelanguage.googleapis.com';
    case 'ollama':
      return 'http://localhost:11434';
    default:
      return 'https://api.openai.com/v1';
  }
});
const keyStateText = computed(() => {
  if (form.value.apiKey.trim()) {
    return t('已填写新 Key');
  }
  if (form.value.apiKeyMasked) {
    return form.value.apiKeyMasked;
  }
  return t('未配置');
});

const metricCards = computed(() => {
  const enabled = instances.value.filter((item) => item.status === 'active').length;
  const chatModels = instances.value.filter((item) => item.status === 'active' && item.capabilities.includes('chat')).length;
  const configuredProviders = new Set(instances.value.map((item) => item.providerId)).size;
  return [
    { key: 'total', icon: '<svg viewBox="0 0 24 24"><rect x="4" y="4" width="16" height="16" rx="2" /><rect x="9" y="9" width="6" height="6" /><line x1="9" y1="1" x2="9" y2="4" /><line x1="15" y1="1" x2="15" y2="4" /><line x1="9" y1="20" x2="9" y2="23" /><line x1="15" y1="20" x2="15" y2="23" /><line x1="20" y1="9" x2="23" y2="9" /><line x1="20" y1="15" x2="23" y2="15" /><line x1="1" y1="9" x2="4" y2="9" /><line x1="1" y1="15" x2="4" y2="15" /></svg>', label: t('模型配置'), value: instances.value.length, note: t('当前主账号下的模型实例') },
    { key: 'active', icon: '<svg viewBox="0 0 24 24"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" /></svg>', label: t('已启用'), value: enabled, note: t('可被后续 runtime 路由选用') },
    { key: 'chat', icon: '<svg viewBox="0 0 24 24"><path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4z" /><path d="M8 9h8M8 13h5" /></svg>', label: t('对话模型'), value: chatModels, note: t('仅使用企业已配置的模型') },
    { key: 'providers', icon: '<svg viewBox="0 0 24 24"><rect width="20" height="8" x="2" y="2" rx="2" ry="2" /><rect width="20" height="8" x="2" y="14" rx="2" ry="2" /><line x1="6" x2="6.01" y1="6" y2="6" /><line x1="6" x2="6.01" y1="18" y2="18" /></svg>', label: t('供应商'), value: configuredProviders, note: t('OpenAI / Azure OpenAI / Qwen / DeepSeek 等') },
  ];
});

const filteredInstances = computed(() => {
  const keyword = filters.value.keyword.trim().toLowerCase();
  return instances.value.filter((row) => {
    const hitKeyword =
      !keyword ||
      [row.displayName, row.modelName, row.baseUrl, row.providerName].some((field) =>
        field.toLowerCase().includes(keyword),
      );
    const hitProvider = !filters.value.providerId || row.providerId === filters.value.providerId;
    const hitStatus = !filters.value.status || row.status === filters.value.status;
    return hitKeyword && hitProvider && hitStatus;
  });
});
const filteredStandaloneInstances = computed(() => filteredInstances.value.filter((item) => !item.groupId));
const filteredGroups = computed(() => {
  const keyword = filters.value.keyword.trim().toLowerCase();
  return groups.value.filter((group) => {
    const children = filteredInstances.value.filter((item) => item.groupId === group.id);
    const groupMatches = (!keyword || [group.name, group.baseUrl].some((value) => value.toLowerCase().includes(keyword)))
      && (!filters.value.providerId || group.providerId === filters.value.providerId)
      && (!filters.value.status || group.status === filters.value.status);
    return groupMatches || children.length > 0;
  });
});

function providerInitial(name: string) {
  return (name || 'M').slice(0, 1).toUpperCase();
}

function resetTestState(text = t('保存模型配置后可测试。')) {
  testResultText.value = text;
  testResultType.value = 'idle';
  testImageUrl.value = '';
}

/** 参考 dsh 的模型库交互：带凭据探测 provider 真实可用模型，弹出列表供点选。 */
async function openModelPicker() {
  if (!currentProvider.value) {
    message.warning(t('请先选择供应商'));
    return;
  }
  if (!form.value.baseUrl.trim()) {
    message.warning(t('请先填写 Base URL'));
    return;
  }
  // Ollama 本地部署无需 Key；编辑已保存配置时 Key 留空将由后端取已存密钥解密复用，
  // 无需每次重新输入（否则会强制用户重填 API Key）。
  const needsKey = currentProvider.value.providerType !== 'ollama' && !form.value.apiKey.trim() && !form.value.id;
  if (needsKey) {
    message.warning(t('请先填写 API Key 以获取模型列表'));
    return;
  }
  discoverLoading.value = true;
  modelPickerVisible.value = true;
  pickedModelIds.value = [];
  try {
    discoveredModels.value = await discoverProviderModels({
      providerType: currentProvider.value.providerType,
      baseUrl: form.value.baseUrl.trim(),
      apiKey: form.value.apiKey,
      apiVersion: form.value.apiVersion,
      instanceId: form.value.id || '',
    });
    if (!discoveredModels.value.length) {
      message.warning(t('未获取到模型列表，请检查凭据是否有效，或手动输入模型 ID'));
    }
  } catch (error) {
    message.error(readError(error, t('获取模型列表失败')));
  } finally {
    discoverLoading.value = false;
  }
}

/** 弹窗内切换单个模型的勾选状态（多选） */
function togglePickModel(id: string) {
  const idx = pickedModelIds.value.indexOf(id);
  if (idx >= 0) {
    pickedModelIds.value.splice(idx, 1);
  } else {
    pickedModelIds.value.push(id);
  }
}

/** 弹窗「确定」：单选填入表单；多选基于当前配置批量创建实例。 */
async function confirmPickModels() {
  const picked = pickedModelIds.value;
  if (!picked.length) {
    message.warning(t('请先选择模型'));
    return;
  }
  // 单选：保留原行为，把模型 ID 填入输入框
  if (picked.length === 1) {
    form.value.modelName = picked[0];
    modelPickerVisible.value = false;
    message.success(t('已选择模型：{name}', { name: picked[0] }));
    return;
  }
  if (!form.value.providerId) {
    message.warning(t('请先选择供应商'));
    return;
  }
  const baseDisplay = form.value.displayName.trim();
  bulkSaving.value = true;
  try {
    let created = 0;
    const failures: string[] = [];
    for (const modelId of picked) {
      const payload = buildModelPayload();
      payload.modelName = modelId;
      // displayName 加模型名后缀以区分同批创建的多个实例
      payload.displayName = baseDisplay ? `${baseDisplay} · ${modelId}` : modelId;
      try {
        await createModelInstance(payload);
        created += 1;
      } catch (error) {
        failures.push(`${modelId}: ${readError(error, '')}`);
      }
    }
    await reload();
    if (created === picked.length) {
      message.success(t('已批量创建 {n} 个模型', { n: created }));
    } else if (created > 0) {
      message.warning(t('批量创建完成：成功 {ok} 个，失败 {fail} 个', { ok: created, fail: failures.length }));
    } else {
      message.error(t('批量创建失败：{msg}', { msg: failures[0] || '未知错误' }));
    }
  } finally {
    bulkSaving.value = false;
    modelPickerVisible.value = false;
    pickedModelIds.value = [];
  }
}

function recommendedImageRuntime(provider?: ModelProviderItem): ImageRuntimeKind {
  if (provider?.providerType === 'azure_openai') return 'azure_openai_images';
  return 'openai_images';
}

function defaultProviderDisplayName(provider: ModelProviderItem) {
  return `${provider.name} ${t('模型')}`;
}

function isAutoProviderDisplayName(value: string, previousProvider?: ModelProviderItem) {
  const normalized = value.trim();
  if (!normalized) {
    return true;
  }
  if (previousProvider && normalized === defaultProviderDisplayName(previousProvider)) {
    return true;
  }
  return providers.value.some((provider) => normalized === defaultProviderDisplayName(provider));
}

function handleProviderChange(providerId: string, previousProviderId?: string) {
  const provider = providerMap.value.get(providerId);
  if (!provider) {
    return;
  }
  const previousProvider = previousProviderId ? providerMap.value.get(previousProviderId) : undefined;
  const baseUrl = form.value.baseUrl.trim();
  const shouldUseProviderBaseUrl = !baseUrl || Boolean(previousProvider?.defaultBaseUrl && baseUrl === previousProvider.defaultBaseUrl);
  if (shouldUseProviderBaseUrl) {
    form.value.baseUrl = provider.defaultBaseUrl;
  }
  if (provider.providerType === 'azure_openai' && !form.value.apiVersion) {
    form.value.apiVersion = '2024-10-21';
  }
  if (hasImageCapability.value) {
    form.value.runtimeKind = recommendedImageRuntime(provider);
    form.value.imageSettings = {};
  }
  if (isAutoProviderDisplayName(form.value.displayName, previousProvider)) {
    form.value.displayName = defaultProviderDisplayName(provider);
  }
}

function suppressNextProviderChangeTick() {
  suppressProviderChange.value = true;
  void nextTick(() => {
    suppressProviderChange.value = false;
  });
}

function openGroupCreate() { selectedGroupModelId.value = ''; editingGroup.value = null; groupEditorVisible.value = true; }
function openGroupEdit(group: ModelGroupItem) { selectedGroupModelId.value = ''; editingGroup.value = group; groupEditorVisible.value = true; }
function openGroupModelEdit(model: ModelInstanceItem) {
  const group = groups.value.find((item) => item.id === model.groupId);
  if (!group) return;
  selectedGroupModelId.value = model.id;
  editingGroup.value = group;
  groupEditorVisible.value = true;
}
async function onGroupSaved(group: ModelGroupItem) {
  editingGroup.value = group;
  await reload();
}

function openCreate() {
  editorMode.value = 'create';
  suppressNextProviderChangeTick();
  form.value = defaultForm();
  const firstProvider = providers.value.find((item) => item.status === 'active');
  if (firstProvider) {
    form.value.providerId = firstProvider.id;
    form.value.baseUrl = firstProvider.defaultBaseUrl;
    form.value.displayName = defaultProviderDisplayName(firstProvider);
  }
  resetTestState(t('新增配置保存后可测试。'));
  editorVisible.value = true;
}

function openEdit(row: ModelInstanceItem) {
  editorMode.value = 'edit';
  suppressNextProviderChangeTick();
  form.value = {
    id: row.id,
    providerId: row.providerId,
    orgId: row.orgId,
    displayName: row.displayName,
    modelName: row.modelName,
    baseUrl: row.baseUrl,
    apiVersion: row.apiVersion || '',
    apiKey: '',
    apiKeyMasked: row.apiKeyMasked,
    capabilities: [...row.capabilities],
    runtimeKind: row.runtimeKind || recommendedImageRuntime(providerMap.value.get(row.providerId)),
    imageSettings: { ...(row.imageSettings || {}) },
    status: row.status,
    isDefault: false,
  };
  resetTestState(t('可在右侧测试当前已保存的配置。'));
  editorVisible.value = true;
}

/** 解析图片扩展参数 JSON：必须是对象，非法时返回 null。 */
function readExtraParamsJson(): Record<string, unknown> | null {
  try {
    const parsed = JSON.parse(String(form.value.imageSettings.extraParamsJson || '{}').trim() || '{}');
    if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') return null;
    return parsed;
  } catch {
    return null;
  }
}

/** 校验模型表单：返回需要提示的错误文案，通过时返回 null。 */
function validateModelForm(): string | null {
  if (!form.value.providerId || !form.value.displayName.trim() || !form.value.modelName.trim()) {
    return t('请补齐供应商、显示名称和模型 ID');
  }
  if (isAzureProvider.value && !form.value.apiVersion.trim()) {
    return t('Azure OpenAI 需要填写 API Version');
  }
  if (hasImageCapability.value && form.value.runtimeKind === 'custom_images') {
    return readExtraParamsJson() ? null : t('请输入有效的 JSON 对象');
  }
  return null;
}

/** 组装模型实例保存载荷：能力相关字段按是否启用图片能力取值。 */
function buildModelPayload(): ModelInstancePayload {
  return {
    providerId: form.value.providerId,
    orgId: form.value.orgId,
    displayName: form.value.displayName.trim(),
    modelName: form.value.modelName.trim(),
    baseUrl: form.value.baseUrl.trim(),
    apiVersion: form.value.apiVersion.trim(),
    apiKey: form.value.apiKey.trim(),
    capabilities: form.value.capabilities.length ? form.value.capabilities : ['chat'],
    runtimeKind: hasImageCapability.value ? form.value.runtimeKind || recommendedImageRuntime(currentProvider.value) : '',
    imageSettings: hasImageCapability.value ? { ...form.value.imageSettings } : {},
    maxContextTokens: 0,
    status: form.value.status,
    isDefault: false,
  };
}

async function saveModel() {
  const problem = validateModelForm();
  if (problem) {
    message.warning(problem);
    return;
  }
  saving.value = true;
  try {
    const isCreatingFirstModel = editorMode.value === 'create' && instances.value.length === 0;
    const payload = buildModelPayload();
    const saved = editorMode.value === 'create'
      ? await createModelInstance(payload)
      : await updateModelInstance(form.value.id, payload);
    await reload();
    openEdit(saved);
    testResultText.value = t('模型配置已保存，可以继续测试。');
    testResultType.value = 'success';
    if (isCreatingFirstModel) {
      showFirstModelTrafficAllocationPrompt();
    } else {
      message.success(t('模型配置已保存'));
    }
  } catch (error) {
    message.error(readError(error, t('保存失败')));
  } finally {
    saving.value = false;
  }
}

function showFirstModelTrafficAllocationPrompt() {
  dialog.success({
    title: t('模型已添加'),
    content: t('已添加第一个模型。为了让用户正常使用模型，请前往流量分配页面设置企业总额度和成员额度。'),
    positiveText: t('前往分配流量'),
    negativeText: t('稍后处理'),
    onPositiveClick: () => {
      void router.push('/organizations/traffic?open=quota');
    },
  });
}

async function runTest(row: ModelInstanceItem) {
  openEdit(row);
  window.setTimeout(() => {
    void runEditorTest();
  }, 100);
}

async function runEditorTest() {
  if (!form.value.id) {
    return;
  }
  testing.value = true;
  testResultText.value = '';
  testResultType.value = 'idle';
  testImageUrl.value = '';
  try {
    if (hasImageCapability.value) {
      const result = await testImageModelInstance(form.value.id, testPrompt.value);
      testResultText.value = result.message || (result.success ? t('图片生成测试成功。') : t('图片生成测试失败。'));
      testResultType.value = result.success ? 'success' : 'failed';
      testImageUrl.value = result.imageUrl || '';
      await reload();
      return;
    }
    await streamModelInstanceTest(form.value.id, testPrompt.value, (event) => {
      if (event.type === 'start') {
        testResultText.value = event.message || t('正在连接模型...');
        return;
      }
      if (event.type === 'delta') {
        if (testResultText.value === t('正在连接模型...')) {
          testResultText.value = '';
        }
        testResultText.value += event.content || '';
        return;
      }
      if (event.type === 'error') {
        testResultText.value = event.message || t('测试失败');
        testResultType.value = 'failed';
        return;
      }
      if (event.type === 'done') {
        if (!testResultText.value) {
          testResultText.value = event.message || t('模型连接测试成功。');
        }
        testResultType.value = 'success';
      }
    });
    if (testResultType.value === 'idle') {
      testResultType.value = 'success';
    }
    await reload();
  } catch (error) {
    testResultText.value = readError(error, t('测试失败'));
    testResultType.value = 'failed';
  } finally {
    testing.value = false;
  }
}

function confirmDelete(row: ModelInstanceItem) {
  if (!window.confirm(t('确认删除「{name}」？删除后后续路由将不能再使用该模型配置。', { name: row.displayName }))) {
    return;
  }
  deleteModelInstance(row.id)
    .then(async () => {
      await reload();
    })
    .catch((error) => {
      window.alert(readError(error, t('删除失败')));
    });
}

function confirmDeleteFromEditor() {
  const row = instances.value.find((item) => item.id === form.value.id);
  if (!row) {
    return;
  }
  if (!window.confirm(t('确认删除「{name}」？删除后后续路由将不能再使用该模型配置。', { name: row.displayName }))) {
    return;
  }
  deleteModelInstance(row.id)
    .then(async () => {
      editorVisible.value = false;
      await reload();
    })
    .catch((error) => {
      window.alert(readError(error, t('删除失败')));
    });
}

async function reload() {
  loading.value = true;
  try {
    const [providerRows, instanceRows, groupRows, allocationOverview] = await Promise.all([
      fetchModelProviders(),
      fetchModelInstances(),
      fetchModelGroups(),
      fetchTrafficAllocationOverview().catch(() => null),
    ]);
    providers.value = providerRows;
    instances.value = instanceRows;
    groups.value = groupRows;
    if (allocationOverview) {
      orgQuota.value = allocationOverview.orgPolicy.totalTokens;
    }
  } catch (error) {
    window.alert(readError(error, t('模型配置加载失败')));
  } finally {
    loading.value = false;
  }
}


function readError(error: unknown, fallback: string) {
  if (axios.isAxiosError(error)) {
    return String(error.response?.data?.detail || error.message || fallback);
  }
  return fallback;
}

watch(
  () => form.value.providerId,
  (providerId, previousProviderId) => {
    if (suppressProviderChange.value || !providerId || providerId === previousProviderId) {
      return;
    }
    handleProviderChange(providerId, previousProviderId);
  },
);

watch(
  () => hasImageCapability.value,
  (enabled) => {
    if (enabled) {
      form.value.runtimeKind = form.value.runtimeKind || recommendedImageRuntime(currentProvider.value);
      if (testPrompt.value === t('测试模型默认提示')) {
        testPrompt.value = t('测试模型图片提示');
      }
    } else if (testPrompt.value === t('测试模型图片提示')) {
      testPrompt.value = t('测试模型默认提示');
    }
    resetTestState(editorMode.value === 'edit' ? t('可在右侧测试当前已保存的配置。') : t('保存模型配置后可测试。'));
  },
);

onMounted(reload);
</script>

<style scoped>
.model-page {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.shell-card {
  border-radius: 14px;
  border: 1px solid var(--mg-border);
  background: var(--mg-bg-surface);
  box-shadow: 0 6px 20px rgba(16, 38, 84, 0.05);
}

.metrics-row {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.metric-card,
.list-card {
  border-radius: 8px;
}

.list-card {
  width: 100%;
  margin: 0 0 0;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.list-card :deep(.n-card__content) {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.metric-card {
  border: 1px solid var(--mg-border);
  background: var(--mg-bg-surface);
  box-shadow: 0 4px 12px rgba(29, 54, 110, 0.04);
}

.metric-main {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}

.metric-body {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.metric-icon {
  width: 44px;
  height: 44px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  font-size: 13px;
  font-weight: 700;
}

.metric-icon :deep(svg) {
  width: 20px;
  height: 20px;
  fill: none;
  stroke: currentColor;
  stroke-width: 2;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.metric-icon-total {
  color: var(--mg-brand);
  background: var(--mg-brand-soft);
}

.metric-icon-active {
  color: var(--mg-success-text);
  background: var(--mg-success-bg);
}

.metric-icon-default {
  color: var(--mg-warning-text);
  background: var(--mg-warning-bg);
}

.metric-icon-providers {
  color: var(--mg-accent-violet-text);
  background: var(--mg-accent-violet-bg);
}

.metric-label {
  color: var(--mg-text-2);
  font-size: 12px;
  line-height: 1.3;
}

.metric-value {
  color: var(--mg-text-1);
  font-size: 24px;
  font-weight: 600;
  line-height: 1.1;
}

.metric-note {
  margin-top: 6px;
  color: var(--mg-text-2);
  font-size: 12px;
}

.filter-left {
  flex-wrap: wrap;
}

.keyword-input {
  width: 360px;
}

.filter-right {
  flex-wrap: wrap;
}

.filter-right :deep(svg) {
  width: 15px;
  height: 15px;
  fill: none;
  stroke: currentColor;
  stroke-width: 2;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.list-filter-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 0 32px 16px;
  margin: 0 -32px 16px;
  border-bottom: 1px solid var(--mg-border);
}

.list-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
  scrollbar-gutter: stable;
}

.model-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}

.model-config-card {
  min-height: 220px;
  padding: 16px;
  border: 1px solid rgba(28, 45, 82, 0.1);
  border-radius: 8px;
  background: var(--mg-bg-surface);
  color: inherit;
  text-align: left;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 10px;
  transition:
    border-color 0.2s ease,
    box-shadow 0.2s ease,
    background-color 0.2s ease;
}

.model-config-card:hover {
  border-color: rgba(54, 106, 255, 0.36);
  box-shadow: 0 10px 28px rgba(33, 58, 126, 0.1);
}

.card-head,
.card-actions,
.card-bottom {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.state-tags {
  justify-content: flex-end;
}

.provider-badge {
  color: var(--mg-brand);
  font-size: 12px;
  font-weight: 700;
}

.card-body {
  min-height: 52px;
}

.card-title {
  color: var(--mg-text-1);
  font-size: 16px;
  font-weight: 800;
}

.card-model-id {
  margin-top: 3px;
  color: var(--mg-text-2);
  font-family: "SFMono-Regular", Consolas, "Liberation Mono", monospace;
  font-size: 12px;
}

.capability-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  min-height: 24px;
  margin-top: 2px;
}

.capability-tag {
  background: var(--mg-bg-subtle);
}

.card-footnote {
  margin-top: auto;
  color: var(--mg-text-3);
  font-size: 12px;
}

.test-summary div {
  display: grid;
  gap: 2px;
}

.test-summary span {
  color: var(--mg-text-3);
  font-size: 12px;
}

.test-image-preview {
  width: 100%;
  max-height: 260px;
  border: 1px solid var(--mg-border);
  border-radius: 8px;
  object-fit: contain;
  background: var(--mg-bg-subtle);
}

.test-summary strong {
  min-width: 0;
  overflow: hidden;
  color: var(--mg-text-1);
  font-size: 12px;
  font-weight: 650;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.card-bottom {
  margin-top: 2px;
}

.card-actions {
  justify-content: flex-start;
}

.add-model-card {
  display: grid;
  min-height: 246px;
  place-content: center;
  justify-items: center;
  border-style: dashed;
  background: rgba(247, 250, 255, 0.8);
  text-align: center;
}

.add-symbol {
  display: grid;
  width: 38px;
  height: 38px;
  place-items: center;
  border-radius: 8px;
  background: var(--mg-brand);
  color: #fff;
  font-size: 26px;
  line-height: 1;
}

.add-title {
  margin-top: 12px;
  color: var(--mg-text-1);
  font-weight: 800;
}

.add-copy {
  max-width: 230px;
  margin-top: 6px;
  color: var(--mg-text-2);
  font-size: 12px;
  line-height: 1.5;
}

.editor-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 280px;
  gap: 18px;
}

.editor-layout.single-column {
  grid-template-columns: minmax(0, 1fr);
}

.test-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 14px;
  border: 1px solid rgba(28, 45, 82, 0.1);
  border-radius: 8px;
  background: var(--mg-bg-surface);
}

.test-title {
  color: var(--mg-text-1);
  font-size: 15px;
  font-weight: 800;
}

.test-summary {
  display: grid;
  gap: 10px;
}

.test-result {
  min-height: 54px;
  padding: 10px;
  border-radius: 8px;
  background: var(--mg-bg-surface);
  color: var(--mg-text-2);
  font-size: 12px;
  line-height: 1.5;
}

.test-result.success {
  color: var(--mg-success-text);
  background: var(--mg-success-bg);
}

.test-result.failed {
  color: var(--mg-danger-text);
  background: var(--mg-danger-bg);
}

.model-picker-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  max-height: 420px;
  overflow: auto;
  padding: 2px;
}

.model-picker-item {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 10px 34px 10px 12px;
  border: 1px solid rgba(28, 45, 82, 0.12);
  border-radius: 8px;
  background: var(--mg-bg-surface);
  color: inherit;
  text-align: left;
  cursor: pointer;
  transition:
    border-color 0.15s ease,
    box-shadow 0.15s ease,
    background-color 0.15s ease;
}

.model-picker-item:hover {
  border-color: rgba(54, 106, 255, 0.4);
  box-shadow: 0 6px 18px rgba(33, 58, 126, 0.08);
  background: var(--mg-bg-surface-hover);
}

.model-picker-item.is-selected {
  border-color: #366aff;
  box-shadow: 0 0 0 1px #366aff inset, 0 6px 18px rgba(54, 106, 255, 0.14);
  background: rgba(54, 106, 255, 0.06);
}

.model-picker-item.is-selected .mp-check {
  opacity: 1;
}

.mp-check {
  position: absolute;
  top: 10px;
  right: 10px;
  display: inline-flex;
  width: 18px;
  height: 18px;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: #366aff;
  color: #fff;
  opacity: 0;
  transition: opacity 0.15s ease;
}

.mp-check svg {
  width: 12px;
  height: 12px;
  display: block;
}

.mp-footer-hint {
  align-self: center;
  color: var(--mg-text-3);
  font-size: 12px;
  min-width: 0;
}

.mp-id {
  color: var(--mg-text-1);
  font-family: "SFMono-Regular", Consolas, "Liberation Mono", monospace;
  font-size: 13px;
  font-weight: 600;
  word-break: break-all;
}

.mp-owner {
  color: var(--mg-text-3);
  font-size: 12px;
}

</style>
