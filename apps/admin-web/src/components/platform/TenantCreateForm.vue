<template>
  <n-form ref="formRef" :model="form" label-placement="top" @submit.prevent="handleSubmit">
    <n-form-item :label="t('企业名称')" path="orgName" :rule="requiredRule(t('请输入企业名称'))">
      <n-input v-model:value="form.orgName" :placeholder="t('例如：墨攻科技')" @keydown.enter.prevent="handleSubmit" />
    </n-form-item>

    <div class="form-grid">
      <n-form-item :label="t('管理员账号')" path="adminUsername" :rule="requiredRule(t('请输入管理员账号'))">
        <n-input v-model:value="form.adminUsername" :placeholder="t('登录账号')" @keydown.enter.prevent="handleSubmit" />
      </n-form-item>
      <n-form-item :label="t('管理员密码')" path="adminPassword" :rule="passwordRule">
        <n-input
          v-model:value="form.adminPassword"
          type="password"
          show-password-on="click"
          :placeholder="t('至少 6 位')"
          @keydown.enter.prevent="handleSubmit"
        />
      </n-form-item>
    </div>

    <n-form-item :label="t('管理员显示名')">
      <n-input v-model:value="form.adminDisplayName" :placeholder="t('可选')" @keydown.enter.prevent="handleSubmit" />
    </n-form-item>

    <n-collapse class="optional-block">
      <n-collapse-item :title="t('可选配置（员工账号 / 模型 / 搜索 / 配额）')" name="optional">
        <div class="form-grid">
          <n-form-item :label="t('员工账号')">
            <n-input v-model:value="form.employeeUsername" :placeholder="t('可选')" />
          </n-form-item>
          <n-form-item :label="t('员工姓名')">
            <n-input v-model:value="form.employeeName" :placeholder="t('可选')" />
          </n-form-item>
        </div>
        <n-form-item :label="t('员工密码')">
          <n-input v-model:value="form.employeePassword" type="password" show-password-on="click" :placeholder="t('可选')" />
        </n-form-item>

        <div class="form-grid">
          <n-form-item :label="t('默认模型')">
            <n-input v-model:value="form.model" :placeholder="t('可选，模型名称')" />
          </n-form-item>
          <n-form-item :label="t('附加模型')">
            <n-input v-model:value="additionalModelsText" :placeholder="t('可选，逗号分隔')" />
          </n-form-item>
        </div>

        <n-form-item :label="t('企业总 Token')">
          <n-input-number v-model:value="form.quota.totalTokens" :min="0" :placeholder="t('0 表示不限额')" style="width: 100%" />
        </n-form-item>
        <p class="field-hint">{{ t('填写 0 或留空表示不限额；不限额时不限制成员与企业用量。') }}</p>
        <n-form-item :label="t('成员默认 Token')">
          <n-input-number v-model:value="form.quota.defaultUserTokens" :min="0" :placeholder="t('0 表示不限额')" style="width: 100%" />
        </n-form-item>
      </n-collapse-item>
    </n-collapse>

    <n-space justify="end" :size="12" class="form-actions">
      <n-button :disabled="submitting" @click="emit('cancel')">{{ t('取消') }}</n-button>
      <n-button type="primary" :loading="submitting" attr-type="submit">{{ t('创建租户') }}</n-button>
    </n-space>
  </n-form>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from 'vue';
import type { FormInst, FormItemRule } from 'naive-ui';
import { t } from '@/composables/i18n';
import type { TenantCreatePayload } from '@/api/platform';

const props = defineProps<{
  submitting?: boolean;
}>();
const emit = defineEmits<{
  submit: [payload: TenantCreatePayload];
  cancel: [];
}>();

const formRef = ref<FormInst | null>(null);

const form = reactive({
  orgName: '',
  adminUsername: '',
  adminPassword: '',
  adminDisplayName: '',
  employeeUsername: '',
  employeePassword: '',
  employeeName: '',
  model: '',
  additionalModels: '',
  quota: {
    totalTokens: null as number | null,
    defaultUserTokens: null as number | null,
  },
});

const additionalModelsText = computed({
  get: () => form.additionalModels,
  set: (value: string) => {
    form.additionalModels = value;
  },
});

function requiredRule(messageText: string): FormItemRule {
  return {
    required: true,
    trigger: ['blur', 'input'],
    validator: (_rule, value: string) => {
      if (!String(value ?? '').trim()) return new Error(messageText);
      return true;
    },
  };
}

const passwordRule: FormItemRule = {
  trigger: ['blur', 'input'],
  validator: (_rule, value: string) => {
    if (String(value ?? '').trim().length < 6) return new Error(t('管理员密码至少 6 位'));
    return true;
  },
};

function buildPayload(): TenantCreatePayload {
  const payload: TenantCreatePayload = {
    orgName: form.orgName.trim(),
    adminUsername: form.adminUsername.trim(),
    adminPassword: form.adminPassword,
  };
  if (form.adminDisplayName.trim()) payload.adminDisplayName = form.adminDisplayName.trim();
  if (form.employeeUsername.trim()) {
    payload.employee = { username: form.employeeUsername.trim() };
    if (form.employeePassword) payload.employee.password = form.employeePassword;
    if (form.employeeName.trim()) payload.employee.name = form.employeeName.trim();
  }
  if (form.model.trim()) payload.model = form.model.trim();
  const additional = form.additionalModels
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
  if (additional.length) payload.additionalModels = additional;
  if (form.quota.totalTokens !== null || form.quota.defaultUserTokens !== null) {
    payload.quota = {
      totalTokens: form.quota.totalTokens ?? 0,
      defaultUserTokens: form.quota.defaultUserTokens ?? 0,
    };
  }
  return payload;
}

async function handleSubmit() {
  if (props.submitting) return;
  try {
    await formRef.value?.validate();
  } catch {
    return;
  }
  emit('submit', buildPayload());
}

defineExpose({
  reset() {
    form.orgName = '';
    form.adminUsername = '';
    form.adminPassword = '';
    form.adminDisplayName = '';
    form.employeeUsername = '';
    form.employeePassword = '';
    form.employeeName = '';
    form.model = '';
    form.additionalModels = '';
    form.quota.totalTokens = null;
    form.quota.defaultUserTokens = null;
    formRef.value?.restoreValidation();
  },
});
</script>

<style scoped>
.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0 14px;
}

.optional-block {
  margin: 4px 0 16px;
}

.field-hint {
  margin: -6px 0 12px;
  color: #7b879f;
  font-size: 12px;
  line-height: 1.6;
}

.form-actions {
  margin-top: 8px;
}

@media (max-width: 620px) {
  .form-grid {
    grid-template-columns: 1fr;
  }
}
</style>
