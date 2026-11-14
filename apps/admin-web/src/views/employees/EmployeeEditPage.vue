<template>
  <div class="employee-edit-page">
    <n-card :bordered="false" class="content-card shell-card">
      <template #header>
        <div class="content-card-header">
          <div>
            <div class="content-title">{{ isCreate ? t('新建数字员工') : t('编辑数字员工') }}</div>
            <div class="section-muted">{{ t('配置员工档案、能力范围与资源边界。') }}</div>
          </div>
          <n-tag :type="form.status === 'active' ? 'success' : 'default'" round>{{ statusLabel(form.status) }}</n-tag>
        </div>
      </template>

      <template #footer>
        <div class="step-actions">
          <n-button secondary @click="backToList">{{ t('返回') }}</n-button>
          <n-button type="primary" :loading="saving" @click="save">{{ isCreate ? t('创建') : t('保存') }}</n-button>
        </div>
      </template>

      <div v-if="loading" class="loading-placeholder">
        <n-skeleton text :repeat="8" />
      </div>
      <template v-else>
        <n-form ref="formRef" :model="form" :rules="rules" label-placement="top">
          <n-grid :cols="2" :x-gap="18">
            <n-form-item-gi :label="t('名称')" path="name">
              <n-input v-model:value="form.name" :placeholder="t('例如：数据分析助手')" />
            </n-form-item-gi>
            <n-form-item-gi :label="t('启用状态')">
              <n-switch v-model:value="enabledSwitch">
                <template #checked>{{ t('启用') }}</template>
                <template #unchecked>{{ t('停用') }}</template>
              </n-switch>
            </n-form-item-gi>
          </n-grid>

          <n-form-item :label="t('说明')" path="description">
            <n-input v-model:value="form.description" type="textarea" :autosize="{ minRows: 2, maxRows: 4 }" :placeholder="t('描述这个员工负责的工作。')" />
          </n-form-item>

          <div class="section-head">
            <div>
              <div class="section-title">{{ t('能力开关') }}</div>
              <div class="section-muted">{{ t('开启后员工可使用的 Agent 能力域。') }}</div>
            </div>
          </div>
          <n-grid :cols="5" :x-gap="18" :y-gap="12">
            <n-form-item-gi v-for="cap in capabilityOptions" :key="cap.key" :label="cap.label">
              <n-switch v-model:value="form.capabilities[cap.key]" />
            </n-form-item-gi>
          </n-grid>

          <div class="section-head">
            <div>
              <div class="section-title">{{ t('工具范围') }}</div>
              <div class="section-muted">{{ t('选择员工可使用的工具集合。') }}</div>
            </div>
          </div>
          <n-grid :cols="2" :x-gap="18">
            <n-form-item-gi :label="t('工具访问模式')">
              <n-radio-group v-model:value="form.toolAccessMode">
                <n-radio-button value="all">{{ t('全部工具') }}</n-radio-button>
                <n-radio-button value="selected">{{ t('指定工具') }}</n-radio-button>
              </n-radio-group>
            </n-form-item-gi>
            <n-form-item-gi v-if="form.toolAccessMode === 'selected'" :label="t('工具')">
              <n-select v-model:value="form.toolIds" multiple :options="toolOptions" filterable :placeholder="t('选择工具')" />
            </n-form-item-gi>
          </n-grid>

          <div class="section-head">
            <div>
              <div class="section-title">{{ t('Skill 范围') }}</div>
              <div class="section-muted">{{ t('选择员工可使用的企业 Skill。') }}</div>
            </div>
          </div>
          <n-grid :cols="2" :x-gap="18">
            <n-form-item-gi :label="t('Skill 访问模式')">
              <n-radio-group v-model:value="form.skillAccessMode">
                <n-radio-button value="all">{{ t('全部 Skill') }}</n-radio-button>
                <n-radio-button value="selected">{{ t('指定 Skill') }}</n-radio-button>
              </n-radio-group>
            </n-form-item-gi>
            <n-form-item-gi v-if="form.skillAccessMode === 'selected'" :label="t('Skill')">
              <n-select v-model:value="form.skillIds" multiple :options="skillOptions" filterable :placeholder="t('选择 Skill')" />
            </n-form-item-gi>
          </n-grid>

          <n-grid :cols="2" :x-gap="18">
            <n-form-item-gi :label="t('知识库 ID')">
              <n-dynamic-tags v-model:value="form.knowledge_base_ids" />
            </n-form-item-gi>
            <n-form-item-gi :label="t('记忆范围')">
              <n-select v-model:value="form.memory_scope" :options="memoryScopeOptions" />
            </n-form-item-gi>
          </n-grid>

          <n-grid :cols="2" :x-gap="18">
            <n-form-item-gi :label="t('模型设置 (JSON)')">
              <n-input v-model:value="modelSettingsText" type="textarea" :autosize="{ minRows: 3, maxRows: 6 }" :placeholder="t('模型设置 JSON，例如 model_instance_id 字段')" />
            </n-form-item-gi>
            <n-form-item-gi :label="t('Harness 配置引用')">
              <n-input v-model:value="form.harness_profile_ref" :placeholder="t('可选')" />
            </n-form-item-gi>
          </n-grid>

          <n-form-item :label="t('成员用户 ID')">
            <n-dynamic-tags v-model:value="form.member_user_ids" />
          </n-form-item>
        </n-form>
      </template>
    </n-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useMessage } from 'naive-ui';
import type { FormInst, FormRules } from 'naive-ui';
import { t } from '@/composables/i18n';
import {
  createEmployee,
  getEmployee,
  getEmployeeCatalogResources,
  updateEmployee,
  type EmployeeAccessMode,
  type EmployeeCapabilityKey,
  type EmployeeCatalogResources,
  type EmployeeItem,
  type EmployeeMemoryScope,
  type EmployeeStatus,
} from '@/api/employees';

interface EmployeeForm {
  name: string;
  description: string;
  status: EmployeeStatus;
  capabilities: Record<EmployeeCapabilityKey, boolean>;
  toolAccessMode: EmployeeAccessMode;
  toolIds: string[];
  skillAccessMode: EmployeeAccessMode;
  skillIds: string[];
  knowledge_base_ids: string[];
  memory_scope: EmployeeMemoryScope;
  harness_profile_ref: string;
  member_user_ids: string[];
}

const router = useRouter();
const route = useRoute();
const message = useMessage();
const formRef = ref<FormInst | null>(null);
const loading = ref(false);
const saving = ref(false);

const capabilityOptions: Array<{ key: EmployeeCapabilityKey; label: string }> = [
  { key: 'content_generation', label: t('内容生成') },
  { key: 'image_generation', label: t('图像生成') },
  { key: 'code_generation', label: t('代码生成') },
  { key: 'browser_automation', label: t('浏览器自动化') },
  { key: 'internal_knowledge', label: t('内部知识') },
];

const resources = ref<EmployeeCatalogResources>({ tools: [], skills: [] });
const toolOptions = computed(() => resources.value.tools.map((item) => ({ label: item.name, value: item.id })));
const skillOptions = computed(() => resources.value.skills.map((item) => ({ label: item.name, value: item.id })));
const memoryScopeOptions = computed(() => [
  { label: t('个人'), value: 'personal' },
  { label: t('项目'), value: 'project' },
  { label: t('部门'), value: 'department' },
]);

const employeeId = computed(() => String(route.params.id || ''));
const isCreate = computed(() => !employeeId.value);

const form = reactive<EmployeeForm>({
  name: '',
  description: '',
  status: 'active',
  capabilities: {
    content_generation: false,
    image_generation: false,
    code_generation: false,
    browser_automation: false,
    internal_knowledge: false,
  },
  toolAccessMode: 'selected',
  toolIds: [],
  skillAccessMode: 'selected',
  skillIds: [],
  knowledge_base_ids: [],
  memory_scope: 'personal',
  harness_profile_ref: '',
  member_user_ids: [],
});

const modelSettingsText = ref('{}');

const enabledSwitch = computed({
  get: () => form.status === 'active',
  set: (value: boolean) => { form.status = value ? 'active' : 'disabled'; },
});

const rules: FormRules = {
  name: { required: true, message: t('请输入员工名称'), trigger: 'blur' },
};

function statusLabel(status: EmployeeStatus): string {
  if (status === 'active') return t('启用');
  if (status === 'disabled') return t('停用');
  return t('已归档');
}

function backToList() {
  router.push('/employees');
}

function parseModelSettings(text: string): Record<string, any> {
  try {
    const parsed = JSON.parse(text || '{}');
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

function toForm(item: EmployeeItem) {
  form.name = item.name;
  form.description = item.description;
  form.status = item.status;
  form.capabilities = {
    content_generation: Boolean(item.capabilities?.content_generation),
    image_generation: Boolean(item.capabilities?.image_generation),
    code_generation: Boolean(item.capabilities?.code_generation),
    browser_automation: Boolean(item.capabilities?.browser_automation),
    internal_knowledge: Boolean(item.capabilities?.internal_knowledge),
  };
  form.toolAccessMode = item.toolAccessMode || 'selected';
  form.toolIds = [...(item.toolIds || [])];
  form.skillAccessMode = item.skillAccessMode || 'selected';
  form.skillIds = [...(item.skillIds || [])];
  form.knowledge_base_ids = [...(item.knowledgeBaseIds || [])];
  form.memory_scope = item.memoryScope || 'personal';
  form.harness_profile_ref = item.harnessProfileRef || '';
  form.member_user_ids = [...(item.memberUserIds || [])];
  modelSettingsText.value = JSON.stringify(item.modelConfig || {}, null, 2);
}

function buildPayload() {
  return {
    name: form.name.trim(),
    description: form.description.trim(),
    status: form.status,
    capabilities: { ...form.capabilities },
    toolAccessMode: form.toolAccessMode,
    toolIds: [...form.toolIds],
    skillAccessMode: form.skillAccessMode,
    skillIds: [...form.skillIds],
    knowledge_base_ids: [...form.knowledge_base_ids],
    memory_scope: form.memory_scope,
    model_settings: parseModelSettings(modelSettingsText.value),
    harness_profile_ref: form.harness_profile_ref.trim(),
    member_user_ids: [...form.member_user_ids],
  };
}

async function save() {
  await formRef.value?.validate();
  saving.value = true;
  try {
    const payload = buildPayload();
    if (isCreate.value) {
      await createEmployee(payload);
      message.success(t('数字员工已创建'));
    } else {
      await updateEmployee(employeeId.value, payload);
      message.success(t('数字员工已保存'));
    }
    backToList();
  } catch (error: any) {
    message.error(error?.response?.data?.detail || t('保存失败'));
  } finally {
    saving.value = false;
  }
}

async function load() {
  loading.value = true;
  try {
    resources.value = await getEmployeeCatalogResources();
    if (!isCreate.value) {
      const item = await getEmployee(employeeId.value);
      toForm(item);
    }
  } catch (error: any) {
    message.error(error?.response?.data?.detail || t('加载员工配置失败'));
  } finally {
    loading.value = false;
  }
}

onMounted(load);
</script>

<style scoped>
.employee-edit-page {
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100%;
  padding: var(--mg-page-padding-y) var(--mg-page-padding-x);
  box-sizing: border-box;
  overflow: hidden;
}

.shell-card {
  border-radius: 14px;
  border: 1px solid var(--mg-border);
  background: var(--mg-bg-surface);
  box-shadow: 0 6px 20px rgba(16, 38, 84, 0.05);
}

.content-card {
  flex: 1;
  min-height: 0;
  min-width: 0;
  overflow: hidden;
}

.content-card :deep(.n-card__content) {
  padding-left: 28px;
  padding-right: 28px;
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  overflow-y: auto;
}

.content-card :deep(.n-card__header),
.content-card :deep(.n-card__footer) {
  padding-left: 28px;
  padding-right: 28px;
}

.loading-placeholder {
  padding: 8px 4px 14px;
}

.content-card-header,
.section-head {
  align-items: center;
  display: flex;
  justify-content: space-between;
  gap: 16px;
}

.section-head {
  margin: 8px 0 4px;
}

.section-muted {
  color: var(--mg-text-2);
  font-size: 13px;
  line-height: 1.5;
  margin-top: 4px;
  max-width: 520px;
}

.content-title,
.section-title {
  color: var(--mg-text-1);
  font-size: 16px;
  font-weight: 700;
}

.step-actions {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 10px;
}
</style>
