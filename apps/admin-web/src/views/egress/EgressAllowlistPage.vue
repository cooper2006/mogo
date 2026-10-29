<script setup lang="ts">
import { computed, h, onMounted, reactive, ref } from 'vue';
import {
  NButton,
  NCard,
  NDataTable,
  NForm,
  NFormItem,
  NInput,
  NModal,
  NPopconfirm,
  NSelect,
  NSpace,
  NSwitch,
  NTag,
  type DataTableColumns,
} from 'naive-ui';
import PageIntro from '@/components/PageIntro.vue';
import { formatAdminDateTime } from '@/composables/adminTimezone';
import {
  createEgressRule,
  deleteEgressRule,
  fetchEgressAllowlist,
  updateEgressRule,
  type EgressRule,
  type EgressScope,
} from '@/api/egress';

const loading = ref(false);
const saving = ref(false);
const rows = ref<EgressRule[]>([]);
const errorMsg = ref('');

const scopeLabel: Record<EgressScope, string> = {
  platform: '平台',
  tenant: '租户',
  tool: '工具',
};

const scopeOptions: { label: string; value: EgressScope }[] = [
  { label: 'platform（平台默认）', value: 'platform' },
  { label: 'tenant（租户级）', value: 'tenant' },
  { label: 'tool（工具例外）', value: 'tool' },
];

async function load() {
  loading.value = true;
  errorMsg.value = '';
  try {
    const data = await fetchEgressAllowlist();
    rows.value = data.items;
  } catch (e) {
    errorMsg.value = String(e);
  } finally {
    loading.value = false;
  }
}

// ---------------------------------------------------------------------------
// 新建 / 编辑弹窗（表单字段严格对齐后端 create/update payload）
// ---------------------------------------------------------------------------

const showModal = ref(false);
const editingId = ref('');
const form = reactive({
  scope: 'tenant' as EgressScope,
  match_domain: '',
  path_prefix: '',
  tool_id: '',
  enabled: true,
  note: '',
});
const formError = ref('');

function resetForm() {
  editingId.value = '';
  form.scope = 'tenant';
  form.match_domain = '';
  form.path_prefix = '';
  form.tool_id = '';
  form.enabled = true;
  form.note = '';
  formError.value = '';
}

function openCreate() {
  resetForm();
  showModal.value = true;
}

function openEdit(rule: EgressRule) {
  editingId.value = rule.entry_id;
  form.scope = rule.scope;
  form.match_domain = rule.match_domain;
  form.path_prefix = rule.path_prefix;
  form.tool_id = rule.tool_id;
  form.enabled = rule.enabled;
  form.note = rule.note;
  formError.value = '';
  showModal.value = true;
}

function validate(): string {
  if (!form.match_domain.trim()) return '域名后缀不能为空（例如 api.example.com）';
  if (form.scope === 'tool' && !form.tool_id.trim()) return '工具级条目需要填写工具 ID';
  return '';
}

async function submit() {
  const problem = validate();
  if (problem) {
    formError.value = problem;
    return;
  }
  saving.value = true;
  formError.value = '';
  const base = {
    match_domain: form.match_domain.trim(),
    path_prefix: form.path_prefix.trim(),
    enabled: form.enabled,
    note: form.note,
  };
  try {
    if (editingId.value) {
      await updateEgressRule(editingId.value, base);
    } else {
      await createEgressRule({
        ...base,
        scope: form.scope,
        tool_id: form.scope === 'tool' ? form.tool_id.trim() : '',
      });
    }
    showModal.value = false;
    await load();
  } catch (e) {
    formError.value = String(e);
  } finally {
    saving.value = false;
  }
}

async function toggleEnabled(rule: EgressRule) {
  try {
    await updateEgressRule(rule.entry_id, { enabled: !rule.enabled });
    await load();
  } catch (e) {
    errorMsg.value = String(e);
  }
}

async function remove(rule: EgressRule) {
  try {
    await deleteEgressRule(rule.entry_id);
    await load();
  } catch (e) {
    errorMsg.value = String(e);
  }
}

const scopeTagType = (scope: EgressScope) =>
  scope === 'platform' ? 'warning' : scope === 'tool' ? 'info' : 'default';

const columns = computed<DataTableColumns<EgressRule>>(() => [
  {
    title: '作用域',
    key: 'scope',
    width: 110,
    render: (row) => h(NTag, { size: 'small', type: scopeTagType(row.scope) }, () => scopeLabel[row.scope] ?? row.scope),
  },
  {
    title: '域名后缀',
    key: 'match_domain',
    minWidth: 180,
    render: (row) => row.match_domain,
  },
  {
    title: '路径前缀',
    key: 'path_prefix',
    width: 130,
    render: (row) => (row.path_prefix ? `/${row.path_prefix}` : '全部路径'),
  },
  {
    title: '工具 ID',
    key: 'tool_id',
    width: 110,
    render: (row) => (row.scope === 'tool' ? row.tool_id : '—'),
  },
  {
    title: '启用',
    key: 'enabled',
    width: 80,
    render: (row) =>
      h(NSwitch, {
        value: row.enabled,
        onUpdateValue: () => toggleEnabled(row),
        size: 'small',
      }),
  },
  {
    title: '说明',
    key: 'note',
    minWidth: 160,
    render: (row) => row.note || '—',
  },
  {
    title: '更新时间',
    key: 'updated_at',
    width: 170,
    render: (row) => formatAdminDateTime(row.updated_at, '-'),
  },
  {
    title: '操作',
    key: 'actions',
    width: 130,
    render: (row) =>
      h(NSpace, { size: 8 }, () => [
        h(NButton, { size: 'small', onClick: () => openEdit(row) }, () => '编辑'),
        h(
          NPopconfirm,
          { onPositiveClick: () => remove(row) },
          {
            trigger: () => h(NButton, { size: 'small', type: 'error' }, () => '删除'),
            default: () => `确认删除条目 ${row.match_domain}？`,
          },
        ),
      ]),
  },
]);

onMounted(load);
</script>

<template>
  <div class="page-container">
    <PageIntro
      title="出站访问控制"
      description="出站白名单（platform / tenant / tool 三层并集）：未命中任一层的出站调用一律拒绝（fail-closed），命中/拒绝均落审计。域名后缀匹配覆盖全部子域，可附加路径前缀。"
      :tags="['038 出站沙箱', '默认拒绝', 'SSRF 防护']"
    />
    <p v-if="errorMsg" style="color: #d03050">{{ errorMsg }}</p>

    <NCard size="small">
      <NSpace justify="space-between" align="center" style="margin-bottom: 12px">
        <span>允许列表（{{ rows.length }} 条）</span>
        <NSpace>
          <NButton size="small" @click="load">刷新</NButton>
          <NButton size="small" type="primary" @click="openCreate">新建条目</NButton>
        </NSpace>
      </NSpace>
      <NDataTable :columns="columns" :data="rows" :loading="loading" :row-key="(row: EgressRule) => row.entry_id" size="small" />
      <p v-if="!loading && !errorMsg && rows.length === 0" style="color: #888">
        暂无白名单条目。空白单时所有出站调用将被拒绝，请先写入必需域名。
      </p>
    </NCard>

    <NModal
      v-model:show="showModal"
      preset="card"
      :title="editingId ? '编辑出站条目' : '新建出站条目'"
      style="width: 560px"
    >
      <NForm label-placement="left" label-width="96px" size="small">
        <NFormItem label="作用域">
          <NSelect v-model:value="form.scope" :options="scopeOptions" :disabled="Boolean(editingId)" />
        </NFormItem>
        <NFormItem label="域名后缀">
          <NInput v-model:value="form.match_domain" placeholder="如 api.example.com（覆盖其全部子域）" />
        </NFormItem>
        <NFormItem v-if="form.scope === 'tool'" label="工具 ID">
          <NInput v-model:value="form.tool_id" placeholder="绑定工具 ID（仅该工具生效）" />
        </NFormItem>
        <NFormItem label="路径前缀">
          <NInput v-model:value="form.path_prefix" placeholder="可选，如 v1（不填则匹配该域全部路径）" />
        </NFormItem>
        <NFormItem label="启用">
          <NSwitch v-model:value="form.enabled" />
        </NFormItem>
        <NFormItem label="说明">
          <NInput v-model:value="form.note" type="textarea" :rows="2" placeholder="备注（可选）" />
        </NFormItem>
      </NForm>
      <p v-if="formError" style="color: #d03050">{{ formError }}</p>
      <template #footer>
        <NSpace justify="end">
          <NButton size="small" @click="showModal = false">取消</NButton>
          <NButton size="small" type="primary" :loading="saving" @click="submit">保存</NButton>
        </NSpace>
      </template>
    </NModal>
  </div>
</template>
<style scoped>
.page-container {
  height: 100%;
  min-height: 0;
}
</style>
