<script setup lang="ts">
// 053-plaza-template-distribution —— 模板管理页（US1 / US2 / US3）。
// 上架（032 门禁 + 001 审批接线）、克隆、版本升级入口；i18n 经 messages 表。
import { computed, h, onMounted, ref } from 'vue';
import {
  NCard, NButton, NTag, NSelect, NEmpty, NSpace, NDataTable, NModal, NInput, NForm, NFormItem, useMessage,
} from 'naive-ui';
import PageIntro from '@/components/PageIntro.vue';
import {
  fetchTemplates, createTemplate, publishTemplate, unpublishTemplate,
  cloneTemplate, upgradeTemplate,
  type TemplateSummary, type TemplateAssetType,
} from '@/api/templates';

const message = useMessage();
const loading = ref(true);
const error = ref('');
const templates = ref<TemplateSummary[]>([]);
const assetType = ref<TemplateAssetType | 'all'>('all');

const typeOptions = [
  { label: '员工模板', value: 'employee_template' },
  { label: 'SOP 模板', value: 'sop_template' },
];

const typeLabels: Record<string, string> = {
  employee_template: '员工模板',
  sop_template: 'SOP 模板',
};

const typeStateLabels: Record<string, string> = {
  draft: '草稿',
  published: '已上架',
  offline: '已下架',
};

const columns = [
  { title: '名称', key: 'name' },
  { title: '类型', key: 'asset_type', render: (row: TemplateSummary) => typeLabels[row.asset_type] || row.asset_type },
  { title: '版本', key: 'version', width: 80 },
  {
    title: '状态', key: 'state', width: 100,
    render: (row: TemplateSummary) => h(
      NTag,
      { size: 'small', type: row.state === 'published' ? 'success' : row.state === 'offline' ? 'warning' : 'default' },
      { default: () => (typeStateLabels[row.state] || row.state) },
    ),
  },
  { title: '描述', key: 'description', ellipsis: { tooltip: true } },
];

async function load() {
  loading.value = true;
  error.value = '';
  try {
    const res = await fetchTemplates(assetType.value === 'all' ? {} : { asset_type: assetType.value });
    templates.value = res.items;
  } catch (e) {
    error.value = String((e as Error).message || e);
  } finally {
    loading.value = false;
  }
}

// 创建模板
const showCreate = ref(false);
const createForm = ref({ name: '', asset_type: 'sop_template' as TemplateAssetType, description: '' });

async function onCreate() {
  if (!createForm.value.name.trim()) {
    message.warning('请填写模板名称');
    return;
  }
  try {
    await createTemplate({
      name: createForm.value.name,
      asset_type: createForm.value.asset_type,
      content: { orchestration: { id: 'new_sop', version: '1', mode: 'graph' }, nodes: [] },
      description: createForm.value.description,
    });
    message.success('模板已创建（草稿）');
    showCreate.value = false;
    await load();
  } catch (e) {
    message.error(String((e as Error).message || e));
  }
}

// 上架 / 下架
async function onPublish(row: TemplateSummary) {
  try {
    await publishTemplate(row.template_id);
    message.success('上架成功（门禁已通过）');
    await load();
  } catch (e) {
    message.error(String((e as Error).message || e));
  }
}

async function onUnpublish(row: TemplateSummary) {
  try {
    await unpublishTemplate(row.template_id);
    message.success('已下架（副本不受影响）');
    await load();
  } catch (e) {
    message.error(String((e as Error).message || e));
  }
}

// 克隆
const showClone = ref(false);
const cloneTarget = ref<TemplateSummary | null>(null);
const cloneForm = ref({ cloner_id: '', name: '' });

function openClone(row: TemplateSummary) {
  cloneTarget.value = row;
  cloneForm.value = { cloner_id: '', name: '' };
  showClone.value = true;
}

async function onClone() {
  if (!cloneTarget.value) return;
  try {
    await cloneTemplate(cloneTarget.value.template_id, {
      cloner_id: cloneForm.value.cloner_id || 'admin',
      name: cloneForm.value.name || undefined,
    });
    message.success('克隆完成，副本已生成');
    showClone.value = false;
    await load();
  } catch (e) {
    message.error(String((e as Error).message || e));
  }
}

onMounted(load);
</script>

<template>
  <div>
    <PageIntro
      title="模板管理"
      description="员工 / SOP 模板上架（032 门禁）、克隆副本与版本升级。"
    />
    <NCard>
      <template #header>
        <NSpace align="center">
          <span>模板列表</span>
          <NSelect
            v-model:value="assetType"
            :options="typeOptions"
            clearable
            placeholder="全部类型"
            style="width: 160px"
            @update:value="load"
          />
          <NButton type="primary" @click="showCreate = true">新建模板</NButton>
          <NButton @click="load">刷新</NButton>
        </NSpace>
      </template>
      <NEmpty v-if="!loading && templates.length === 0" description="暂无模板" />
      <NDataTable
        v-else
        :columns="columns"
        :data="templates"
        :loading="loading"
        :row-key="(row: TemplateSummary) => row.template_id"
      />
      <NSpace v-if="!loading && templates.length > 0" style="margin-top: 16px">
        <template v-for="row in templates" :key="row.template_id">
          <NButton
            v-if="row.state !== 'published'"
            size="small"
            type="primary"
            @click="onPublish(row)"
          >上架</NButton>
          <NButton
            v-if="row.state === 'published'"
            size="small"
            type="warning"
            @click="onUnpublish(row)"
          >下架</NButton>
          <NButton
            v-if="row.state === 'published'"
            size="small"
            @click="openClone(row)"
          >克隆</NButton>
        </template>
      </NSpace>
      <p v-if="error" style="color: #d03050">{{ error }}</p>
    </NCard>

    <NModal v-model:show="showCreate" title="新建模板" preset="card" style="width: 520px">
      <NForm>
        <NFormItem label="名称">
          <NInput v-model:value="createForm.name" placeholder="如：合同审查 SOP" />
        </NFormItem>
        <NFormItem label="类型">
          <NSelect v-model:value="createForm.asset_type" :options="typeOptions" />
        </NFormItem>
        <NFormItem label="描述">
          <NInput v-model:value="createForm.description" type="textarea" />
        </NFormItem>
      </NForm>
      <template #footer>
        <NSpace justify="end">
          <NButton @click="showCreate = false">取消</NButton>
          <NButton type="primary" @click="onCreate">创建</NButton>
        </NSpace>
      </template>
    </NModal>

    <NModal v-model:show="showClone" title="克隆模板" preset="card" style="width: 520px">
      <p v-if="cloneTarget">将克隆「{{ cloneTarget.name }}」到你名下（副本可改，原件只读）。</p>
      <NForm style="margin-top: 12px">
        <NFormItem label="克隆者 ID">
          <NInput v-model:value="cloneForm.cloner_id" placeholder="克隆者标识" />
        </NFormItem>
        <NFormItem label="副本名称">
          <NInput v-model:value="cloneForm.name" placeholder="留空则沿用模板名（自动去重）" />
        </NFormItem>
      </NForm>
      <template #footer>
        <NSpace justify="end">
          <NButton @click="showClone = false">取消</NButton>
          <NButton type="primary" @click="onClone">克隆</NButton>
        </NSpace>
      </template>
    </NModal>
  </div>
</template>
