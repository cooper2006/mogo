<template>
  <n-form label-placement="top">
    <n-grid :cols="2" :x-gap="12">
      <n-grid-item :span="2">
        <n-form-item :label="t('模型供应商')">
          <n-select
            v-model:value="model.providerId"
            :options="providerOptions"
            :loading="providersLoading"
            :placeholder="t('选择模型供应商')"
          />
        </n-form-item>
      </n-grid-item>
      <n-grid-item>
        <n-form-item :label="t('配置名称')">
          <n-input v-model:value="model.displayName" :placeholder="t('例如：企业对话模型')" />
        </n-form-item>
      </n-grid-item>
      <n-grid-item>
        <n-form-item :label="isAzure ? t('Deployment 名称') : t('模型 ID')">
          <n-input v-model:value="model.modelName" :placeholder="modelPlaceholder" />
        </n-form-item>
      </n-grid-item>
      <n-grid-item :span="isAzure ? 1 : 2">
        <n-form-item :label="isAzure ? 'Azure Endpoint' : 'Base URL'" :feedback="baseUrlFeedback">
          <n-input v-model:value="model.baseUrl" :placeholder="baseUrlPlaceholder" />
        </n-form-item>
      </n-grid-item>
      <n-grid-item v-if="isAzure">
        <n-form-item label="API Version">
          <n-input v-model:value="model.apiVersion" placeholder="2024-10-21" />
        </n-form-item>
      </n-grid-item>
      <n-grid-item :span="2">
        <n-form-item label="API Key" :feedback="apiKeyFeedback">
          <n-input v-model:value="model.apiKey" type="password" show-password-on="click" autocomplete="off" />
        </n-form-item>
      </n-grid-item>
    </n-grid>
  </n-form>
</template>

<script setup lang="ts">
import { computed, watch } from 'vue';
import { t } from '@/composables/i18n';
import type { SetupModelProvider } from '@/api/setup';
import { providerLabel } from '@/components/models/providerLabels';
import type { SetupModelForm } from './types';

const props = defineProps<{
  providers: SetupModelProvider[];
  providersLoading: boolean;
}>();
const model = defineModel<SetupModelForm>({ required: true });

const providerOptions = computed(() => props.providers.map((item) => ({ label: providerLabel(item), value: item.id })));
const selectedProvider = computed(() => props.providers.find((item) => item.id === model.value.providerId));
const isAzure = computed(() => selectedProvider.value?.providerType === 'azure_openai');
const providerType = computed(() => selectedProvider.value?.providerType || '');
const modelPlaceholder = computed(() => {
  if (model.value.capability === 'embedding') return t('例如：text-embedding-3-small / text-embedding-v3');
  if (model.value.capability === 'rerank') return t('例如：qwen3-rerank / bge-reranker-v2-m3');
  switch (providerType.value) {
    case 'azure_openai': return t('例如：gpt-4o-mini-prod（Azure 部署名）');
    case 'anthropic': return t('例如：claude-3-5-sonnet-20241022');
    case 'gemini': return t('例如：gemini-1.5-pro');
    case 'ollama': return t('例如：llama3.1');
    default: return t('例如：gpt-4.1 / qwen-plus / deepseek-chat');
  }
});
const baseUrlPlaceholder = computed(() => {
  if (model.value.capability === 'rerank') {
    return t('填写供应商 Base URL；如为自定义服务可填写完整 rerank 地址');
  }
  switch (providerType.value) {
    case 'azure_openai': return 'https://YOUR-RESOURCE-NAME.openai.azure.com';
    case 'anthropic': return 'https://api.anthropic.com';
    case 'gemini': return 'https://generativelanguage.googleapis.com';
    case 'ollama': return 'http://localhost:11434';
    default: return 'https://api.openai.com/v1';
  }
});
const baseUrlFeedback = computed(() => {
  switch (providerType.value) {
    case 'anthropic': return t('Anthropic 官方接口以 /v1/models 拉取模型清单，需填写 x-api-key');
    case 'gemini': return t('Gemini 官方接口，Key 经 URL 参数传递，无需单独 Header');
    case 'ollama': return t('本地部署填写 http://localhost:11434；远程部署替换为对应主机地址，无需 API Key');
    default: return '';
  }
});
const apiKeyFeedback = computed(() => (providerType.value === 'ollama' ? t('Ollama 本地部署默认无需 API Key，可留空') : ''));
const capabilityName = computed(() => ({
  chat: t('对话模型'),
  embedding: t('向量模型'),
  rerank: t('重排模型'),
  vision: t('视觉模型'),
  image: t('文生图模型'),
}[model.value.capability]));

watch(() => model.value.providerId, (providerId, previousId) => {
  const provider = props.providers.find((item) => item.id === providerId);
  if (!provider) return;
  if (!model.value.baseUrl || previousId) model.value.baseUrl = provider.defaultBaseUrl;
  if (!model.value.displayName || previousId) model.value.displayName = `${providerLabel(provider)} ${capabilityName.value}`;
  model.value.apiVersion = provider.providerType === 'azure_openai' ? (model.value.apiVersion || '2024-10-21') : '';
});
</script>
