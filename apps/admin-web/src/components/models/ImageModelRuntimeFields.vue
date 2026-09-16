<template>
  <div class="image-runtime-fields">
    <n-form-item :label="t('接口类型')" required>
      <n-select
        :value="runtimeKind || null"
        :options="runtimeOptions"
        :placeholder="t('选择图片生成接口')"
        @update:value="updateRuntimeKind"
      />
    </n-form-item>
    <n-form-item :label="t('生成尺寸')">
      <n-input
        :value="imageSettings.size || ''"
        :placeholder="t('留空则不传')"
        @update:value="updateSetting('size', $event)"
      />
    </n-form-item>
    <n-collapse class="advanced-settings">
      <n-collapse-item name="advanced">
        <template #header>
          <div class="advanced-title">
            <span>{{ t('高级设置') }}</span>
            <span>{{ t('仅在模型接口需要时填写') }}</span>
          </div>
        </template>
        <div class="advanced-fields">
          <n-form-item :label="t('生成质量')">
            <n-select
              :value="imageSettings.quality || null"
              :options="qualityOptions"
              :placeholder="t('留空则不传')"
              filterable
              tag
              clearable
              @update:value="updateSetting('quality', $event || '')"
            />
          </n-form-item>
          <n-form-item :label="t('输出格式')">
            <n-select
              :value="imageSettings.outputFormat || null"
              :options="outputFormatOptions"
              :placeholder="t('留空则不传')"
              filterable
              tag
              clearable
              @update:value="updateSetting('outputFormat', $event || '')"
            />
          </n-form-item>
          <n-form-item :label="t('返回格式')">
            <n-select
              :value="imageSettings.responseFormat || null"
              :options="responseFormatOptions"
              :placeholder="t('留空则不传')"
              filterable
              tag
              clearable
              @update:value="updateSetting('responseFormat', $event || '')"
            />
          </n-form-item>
          <n-form-item :label="t('生成数量')">
            <n-input-number
              :value="imageSettings.n ?? null"
              :min="1"
              :max="10"
              :placeholder="t('留空则不传')"
              clearable
              style="width: 100%"
              @update:value="updateSetting('n', $event)"
            />
          </n-form-item>
          <n-form-item :label="t('宽高比')">
            <n-input
              :value="imageSettings.ratio || ''"
              :placeholder="t('如: 16:9；留空则不传')"
              @update:value="updateSetting('ratio', $event)"
            />
          </n-form-item>
          <n-form-item v-if="runtimeKind === 'azure_openai_images'" :label="t('Azure 图片 API')">
            <n-select
              :value="imageSettings.apiStyle || 'v1'"
              :options="azureApiOptions"
              @update:value="updateSetting('apiStyle', $event)"
            />
          </n-form-item>
          <template v-if="runtimeKind === 'custom_images'">
            <n-form-item :label="t('请求路径')">
              <n-input
                :value="imageSettings.requestPath || ''"
                placeholder="/images/generations"
                @update:value="updateSetting('requestPath', $event)"
              />
            </n-form-item>
            <n-form-item :label="t('图片 URL 响应路径')">
              <n-input
                :value="imageSettings.responseUrlPath || ''"
                placeholder="data.0.url"
                @update:value="updateSetting('responseUrlPath', $event)"
              />
            </n-form-item>
            <n-form-item :label="t('Base64 响应路径')">
              <n-input
                :value="imageSettings.responseBase64Path || ''"
                placeholder="data.0.b64_json"
                @update:value="updateSetting('responseBase64Path', $event)"
              />
            </n-form-item>
            <n-form-item class="full-width" :label="t('额外请求参数（JSON）')">
              <div class="json-editor">
                <n-input
                  :value="imageSettings.extraParamsJson || ''"
                  type="textarea"
                  :rows="5"
                  placeholder='{ "extra_body": { "response_format": "url" } }'
                  @update:value="updateSetting('extraParamsJson', $event)"
                />
                <n-button size="small" secondary @click="formatExtraParams">{{ t('格式化 JSON') }}</n-button>
              </div>
            </n-form-item>
          </template>
          <div class="runtime-help">
            <div>{{ runtimeHelp }}</div>
            <div>{{ t('仅发送已填写的字段；留空字段不会出现在请求体中。') }}</div>
          </div>
        </div>
      </n-collapse-item>
    </n-collapse>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { NCollapse, NCollapseItem, useMessage } from 'naive-ui';
import { t } from '@/composables/i18n';
import type { ImageModelSettings, ImageRuntimeKind } from '@/api/models';

const props = defineProps<{
  runtimeKind: ImageRuntimeKind | '';
  imageSettings: ImageModelSettings;
  providerType: string;
}>();

const emit = defineEmits<{
  (event: 'update:runtimeKind', value: ImageRuntimeKind): void;
  (event: 'update:imageSettings', value: ImageModelSettings): void;
}>();
const message = useMessage();

const allRuntimeOptions = computed(() => [
  { label: 'OpenAI Images API', value: 'openai_images' },
  { label: 'Azure OpenAI Images API', value: 'azure_openai_images' },
  { label: t('阿里云百炼 DashScope 图片 API'), value: 'dashscope_image' },
  { label: t('自定义图片接口'), value: 'custom_images' },
]);

const runtimeOptions = computed(() => {
  if (props.providerType === 'azure_openai') {
    return allRuntimeOptions.value.filter(item => ['azure_openai_images', 'custom_images'].includes(item.value));
  }
  return allRuntimeOptions.value.filter(item => item.value !== 'azure_openai_images');
});

const qualityOptions = computed(() => [
  { label: t('低（速度优先）'), value: 'low' },
  { label: t('中'), value: 'medium' },
  { label: t('高（质量优先）'), value: 'high' },
  { label: t('自动'), value: 'auto' },
]);

const outputFormatOptions = ['png', 'jpeg', 'webp'].map(value => ({ label: value, value }));
const responseFormatOptions = ['url', 'b64_json'].map(value => ({ label: value, value }));

const azureApiOptions = computed(() => [
  { label: 'OpenAI v1 · /openai/v1/images/generations', value: 'v1' },
  { label: t('Azure Deployment 路径'), value: 'deployment' },
]);

const runtimeHelp = computed(() => {
  if (props.runtimeKind === 'dashscope_image') {
    return t('通义千问图片模型使用 DashScope 原生接口；qwen-image-max/plus 推荐 1664*928（16:9）。');
  }
  if (props.runtimeKind === 'azure_openai_images') {
    return t('模型 ID 请填写 Azure Deployment 名称；GPT Image 1 系列推荐 1536x1024，GPT Image 2 可使用 1536x864。');
  }
  if (props.runtimeKind === 'custom_images') {
    return t('系统自动发送 model 和 prompt，并按配置解析图片响应。');
  }
  return t('适用于实现 /images/generations 的 OpenAI 兼容图片服务。');
});

function updateRuntimeKind(value: ImageRuntimeKind) {
  emit('update:runtimeKind', value);
  if (value === 'custom_images') {
    emit('update:imageSettings', {
      ...props.imageSettings,
      requestPath: props.imageSettings.requestPath || '/images/generations',
      responseUrlPath: props.imageSettings.responseUrlPath || 'data.0.url',
      responseBase64Path: props.imageSettings.responseBase64Path || 'data.0.b64_json',
      extraParamsJson: props.imageSettings.extraParamsJson || '{}',
    });
  }
}

function updateSetting(key: keyof ImageModelSettings, value: string | number | null) {
  emit('update:imageSettings', { ...props.imageSettings, [key]: value });
}

function formatExtraParams() {
  try {
    const parsed = JSON.parse(imageSettingsJson());
    if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') throw new Error();
    updateSetting('extraParamsJson', JSON.stringify(parsed, null, 2));
  } catch {
    message.error(t('请输入有效的 JSON 对象'));
  }
}

function imageSettingsJson() {
  return String(props.imageSettings.extraParamsJson || '{}').trim() || '{}';
}
</script>

<style scoped>
.image-runtime-fields {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 14px;
  padding: 14px 14px 4px;
  border: 1px solid #e6ebf5;
  border-radius: 8px;
  background: #f8faff;
}

.runtime-help {
  grid-column: 1 / -1;
  margin: -2px 0 10px;
  color: #667085;
  font-size: 12px;
  line-height: 1.6;
}

.advanced-settings {
  grid-column: 1 / -1;
  margin-bottom: 12px;
  padding: 0 2px;
}

.advanced-title {
  display: flex;
  align-items: baseline;
  gap: 10px;
}

.advanced-title span:last-child {
  color: #98a2b3;
  font-size: 12px;
  font-weight: 400;
}

.advanced-fields {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 14px;
  padding-top: 8px;
}

.full-width {
  grid-column: 1 / -1;
}

.json-editor {
  display: flex;
  width: 100%;
  align-items: flex-start;
  gap: 8px;
}

.json-editor :deep(.n-input) {
  flex: 1;
}

:global(html.dark) .image-runtime-fields {
  border-color: #263044;
  background: #151c2b;
}

@media (max-width: 700px) {
  .image-runtime-fields {
    grid-template-columns: 1fr;
  }

  .advanced-fields {
    grid-template-columns: 1fr;
  }
}
</style>
