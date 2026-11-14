<script setup lang="ts">
import { t } from '@/composables/i18n';
import { computed, h, onMounted, ref } from 'vue';
import { NButton, NCard, NDataTable, NInput, NSelect, NSpace, NSwitch, NTag, type DataTableColumns } from 'naive-ui';
import PageIntro from '@/components/PageIntro.vue';
import {
  createHookRule,
  deleteHookRule,
  fetchHookRules,
  updateHookRule,
  type HookRule,
  type HookRuleType,
} from '@/api/dsh_hooks';

const loading = ref(false);
const rows = ref<HookRule[]>([]);
const errorMsg = ref('');

// 新建规则表单
const form = ref({
  scope: 'tenant' as 'tool' | 'session' | 'tenant',
  rule_type: 'deny_tool' as HookRuleType,
  tool: '',
  fields: '',
  enabled: true,
});

const ruleTypeOptions = [
  { label: 'deny_tool（拒绝工具）', value: 'deny_tool' },
  { label: 'require_field（要求字段）', value: 'require_field' },
  { label: 'observe（观察）', value: 'observe' },
];

const scopeOptions = [
  { label: 'tool（工具级）', value: 'tool' },
  { label: 'session（会话级）', value: 'session' },
  { label: 'tenant（租户级）', value: 'tenant' },
];

async function load() {
  loading.value = true;
  errorMsg.value = '';
  try {
    rows.value = await fetchHookRules();
  } catch (e) {
    errorMsg.value = String(e);
  } finally {
    loading.value = false;
  }
}

function buildConfig(): Record<string, unknown> {
  const cfg: Record<string, unknown> = {};
  const tool = form.value.tool.trim();
  if (tool) cfg.tool = tool;
  if (form.value.rule_type === 'require_field') {
    const fields = form.value.fields
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean);
    if (fields.length) cfg.fields = fields;
  }
  return cfg;
}

async function submitCreate() {
  const payload = {
    scope: form.value.scope,
    rule_type: form.value.rule_type,
    rule_config: buildConfig(),
    enabled: form.value.enabled,
  };
  try {
    await createHookRule(payload);
    form.value.tool = '';
    form.value.fields = '';
    await load();
  } catch (e) {
    errorMsg.value = String(e);
  }
}

async function toggleEnabled(rule: HookRule) {
  try {
    await updateHookRule(rule.rule_id, { enabled: !rule.enabled });
    await load();
  } catch (e) {
    errorMsg.value = String(e);
  }
}

async function remove(rule: HookRule) {
  if (!window.confirm(`确认删除规则 ${rule.rule_id}？`)) return;
  try {
    await deleteHookRule(rule.rule_id);
    await load();
  } catch (e) {
    errorMsg.value = String(e);
  }
}

const columns: DataTableColumns<HookRule> = [
  {
    title: '规则ID',
    key: 'rule_id',
    minWidth: 120,
  },
  {
    title: '作用域',
    key: 'scope',
    width: 90,
    render: (row) => h(NTag, { size: 'small' }, () => row.scope),
  },
  {
    title: '类型',
    key: 'rule_type',
    width: 120,
    render: (row) => h(NTag, { size: 'small', type: row.rule_type === 'deny_tool' ? 'error' : 'info' }, () => row.rule_type),
  },
  {
    title: '配置',
    key: 'rule_config',
    minWidth: 160,
    render: (row) => JSON.stringify(row.rule_config ?? {}),
  },
  {
    title: '启用',
    key: 'enabled',
    width: 70,
    render: (row) =>
      h(NSwitch, {
        value: row.enabled,
        onUpdateValue: () => toggleEnabled(row),
        size: 'small',
      }),
  },
  {
    title: '租户',
    key: 'tenant_id',
    width: 100,
  },
  {
    title: '操作',
    key: 'actions',
    width: 90,
    render: (row) =>
      h(NButton, { size: 'small', type: 'error', onClick: () => remove(row) }, () => t('删除')),
  },
];

onMounted(load);
</script>

<template>
  <div class="page-container">
    <PageIntro
      :title="t('钩子规则')"
      :description="t('PreToolUse 声明式拦截规则（deny_tool / require_field / observe）；编辑后下一次工具调用即时生效。')"
      :tags="[t('009 钩子拦截'), t('fail-closed')]"
    />
    <NCard title="新建规则" size="small" style="margin-bottom: 16px">
      <NSpace vertical :size="10">
        <NSpace>
          <NSelect v-model:value="form.scope" :options="scopeOptions" style="width: 160px" />
          <NSelect v-model:value="form.rule_type" :options="ruleTypeOptions" style="width: 200px" />
          <NInput v-model:value="form.tool" :placeholder="t('工具名（可选）')" style="width: 180px" />
          <NInput
            v-if="form.rule_type === 'require_field'"
            v-model:value="form.fields"
            placeholder="要求字段（逗号分隔，如 query）"
            style="width: 240px"
          />
        </NSpace>
        <NSpace align="center">
          <NButton type="primary" @click="submitCreate">{{ t('添加规则') }}</NButton>
          <NButton @click="load">{{ t('刷新') }}</NButton>
        </NSpace>
      </NSpace>
    </NCard>
    <NCard title="规则列表" size="small">
      <p v-if="errorMsg" style="color: #d03050">{{ errorMsg }}</p>
      <NDataTable :columns="columns" :data="rows" :loading="loading" :pagination="{ pageSize: 20 }" size="small" />
    </NCard>
  </div>
</template>
