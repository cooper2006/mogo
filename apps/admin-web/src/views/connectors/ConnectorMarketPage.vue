<!-- 041-connector-market US1/US2: 连接器市场（从模板创建向导 + 已安装列表）。

模板来自仓库内 `services/admin-api/app/connector_templates/*.yaml`（FR-001/FR-002），
创建走**既有** external_tools 存储与注入路径（FR-004 同构硬约束），
凭证托管标记按模板如实展示（FR-007，034 落地前诚实降级）。
调用 admin-api `GET/POST /api/connectors/*`。
-->
<template>
  <section class="connector-market">
    <header class="page-header">
      <h1>{{ t('连接器市场') }}</h1>
      <div class="header-actions">
        <n-input
          v-model:value="keyword"
          :placeholder="t('搜索连接器')"
          clearable
          style="width: 220px"
          @keyup.enter="load"
        />
        <n-button secondary :loading="loading" @click="load">{{ t('刷新') }}</n-button>
      </div>
    </header>

    <n-alert v-if="notice" type="warning" closable class="notice" @close="notice = ''">
      {{ notice }}
    </n-alert>
    <n-alert v-if="catalog.loadIssues.length" type="error" class="notice">
      {{ t('部分模板加载失败') }}：{{ catalog.loadIssues.join('；') }}
    </n-alert>

    <n-tabs v-model:value="tab" type="line">
      <n-tab-pane name="catalog" :tab="t('模板目录')">
        <n-spin :show="loading">
          <div class="filters">
            <n-tag
              :type="category === '' ? 'success' : 'default'"
              checkable
              :checked="category === ''"
              @click="selectCategory('')"
            >
              {{ t('全部') }}
            </n-tag>
            <n-tag
              v-for="item in catalog.categories"
              :key="item"
              :type="category === item ? 'success' : 'default'"
              checkable
              :checked="category === item"
              @click="selectCategory(item)"
            >
              {{ categoryLabel(item) }}
            </n-tag>
          </div>

          <n-empty v-if="!filtered.length && !loading" :description="t('暂无匹配的模板')" />
          <div v-else class="cards">
            <n-card v-for="template in filtered" :key="template.id" size="small" class="card">
              <div class="card-head">
                <strong>{{ localize(template.name) }}</strong>
                <n-tag size="small" :bordered="false">{{ categoryLabel(template.category) }}</n-tag>
              </div>
              <p class="desc">{{ localize(template.description) }}</p>
              <div class="meta">
                <n-tag size="small" type="info" :bordered="false">v{{ template.version }}</n-tag>
                <n-tag v-if="template.installed" size="small" type="success" :bordered="false">
                  {{ t('已安装') }}
                </n-tag>
                <span v-if="template.installCount" class="count">
                  {{ t('租户内安装 {n} 次', { n: template.installCount }) }}
                </span>
              </div>
              <n-alert
                v-if="!template.credentialManaged && template.authType !== 'none'"
                type="warning"
                :show-icon="false"
                class="inline-hint"
              >
                {{ t('该连接器的凭证需在 URL 中传递，凭证托管暂不支持；请在创建后于工具详情页手工配置') }}
              </n-alert>
              <div class="card-actions">
                <n-button size="small" type="primary" @click="openInstall(template)">
                  {{ t('从模板创建') }}
                </n-button>
              </div>
            </n-card>
          </div>
        </n-spin>
      </n-tab-pane>

      <n-tab-pane name="installs" :tab="t('已安装连接器')">
        <n-spin :show="installsLoading">
          <n-empty v-if="!installs.length && !installsLoading" :description="t('暂无已安装连接器')" />
          <n-table v-else :single-line="false" size="small">
            <thead>
              <tr>
                <th>{{ t('名称') }}</th>
                <th>{{ t('来源') }}</th>
                <th>{{ t('状态') }}</th>
                <th>{{ t('最近测试') }}</th>
                <th>{{ t('安装时间') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in installs" :key="item.toolId">
                <td>{{ item.name || item.toolId }}</td>
                <td>
                  <n-tag size="small" :bordered="false" :type="item.source === 'template' ? 'info' : 'default'">
                    {{ item.source === 'template' ? (item.templateId || t('模板')) : t('手工创建') }}
                  </n-tag>
                </td>
                <td>{{ item.status === 'active' ? t('启用') : t('停用') }}</td>
                <td>{{ item.lastTestStatus || '—' }}</td>
                <td>{{ item.installedAt || '—' }}</td>
              </tr>
            </tbody>
          </n-table>
        </n-spin>
      </n-tab-pane>
    </n-tabs>

    <n-modal
      v-model:show="installVisible"
      preset="card"
      :title="installTitle"
      style="width: 620px"
      :mask-closable="false"
    >
      <n-form label-placement="top">
        <n-form-item :label="t('连接器名称')">
          <n-input v-model:value="installForm.name" :placeholder="installTitle" />
        </n-form-item>
        <n-form-item
          v-for="param in installTemplate?.params || []"
          :key="param.key"
          :label="localize(param.label) + (param.required ? ' *' : '')"
        >
          <n-input
            v-model:value="installForm.values[param.key]"
            :type="param.secret ? 'password' : 'text'"
            :placeholder="param.example || localize(param.description)"
            show-password-on="click"
          />
          <template #feedback>
            <span class="param-feedback">
              {{ localize(param.description) }}
              <em v-if="param.in === 'path'">{{ t('（创建后调用时再填）') }}</em>
            </span>
          </template>
        </n-form-item>
        <n-form-item :label="t('创建后立即启用')">
          <n-switch v-model:value="installForm.activate" />
        </n-form-item>
        <n-alert v-if="installTemplate && !installTemplate.credentialManaged" type="info" :show-icon="false">
          {{ t('凭证将保留在你填写的 URL 中，托管加密暂不生效（034 凭证加密生效后自动覆盖）') }}
        </n-alert>
      </n-form>
      <template #footer>
        <div class="modal-footer">
          <n-button secondary @click="installVisible = false">{{ t('取消') }}</n-button>
          <n-button type="primary" :loading="installing" @click="onInstall">{{ t('创建连接器') }}</n-button>
        </div>
      </template>
    </n-modal>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue';
import {
  NAlert, NButton, NCard, NEmpty, NForm, NFormItem, NInput, NModal,
  NSpin, NSwitch, NTable, NTabPane, NTabs, NTag, useMessage,
} from 'naive-ui';
import { t, useLocale } from '@/composables/i18n';
import {
  fetchConnectorCatalog, fetchConnectorInstalls, installConnectorTemplate,
  type ConnectorInstallDto, type ConnectorTemplateDto,
} from '@/api/connectorMarket';

const message = useMessage();
const { locale } = useLocale();

const loading = ref(false);
const installsLoading = ref(false);
const installing = ref(false);
const tab = ref<'catalog' | 'installs'>('catalog');
const keyword = ref('');
const category = ref('');
const notice = ref('');
const catalog = ref<{ templates: ConnectorTemplateDto[]; categories: string[]; loadIssues: string[] }>({
  templates: [],
  categories: [],
  loadIssues: [],
});
const installs = ref<ConnectorInstallDto[]>([]);

const installVisible = ref(false);
const installTemplate = ref<ConnectorTemplateDto | null>(null);
const installForm = reactive<{ name: string; values: Record<string, string>; activate: boolean }>({
  name: '',
  values: {},
  activate: false,
});

const CATEGORY_LABELS: Record<string, string> = {
  oa: '协同办公',
  erp: 'ERP 与财务',
  data: '数据与检索',
  devops: '研发运维',
  im: '即时通讯',
};

function categoryLabel(key: string): string {
  return CATEGORY_LABELS[key] ? t(CATEGORY_LABELS[key]) : key;
}

function localize(text?: { zh?: string; en?: string }): string {
  if (!text) return '';
  return (locale.value === 'en-US' ? text.en : text.zh) || text.zh || text.en || '';
}

const filtered = computed(() => {
  const query = keyword.value.trim().toLowerCase();
  return catalog.value.templates.filter((template) => {
    if (category.value && template.category !== category.value) return false;
    if (!query) return true;
    return (
      template.id.toLowerCase().includes(query) ||
      localize(template.name).toLowerCase().includes(query) ||
      localize(template.description).toLowerCase().includes(query)
    );
  });
});

const installTitle = computed(() => (installTemplate.value ? localize(installTemplate.value.name) : ''));

function selectCategory(key: string) {
  category.value = key;
}

async function load() {
  loading.value = true;
  try {
    catalog.value = await fetchConnectorCatalog({ keyword: keyword.value.trim() });
    notice.value = '';
  } catch (error: any) {
    notice.value = t('加载模板失败') + '：' + detailOf(error);
  } finally {
    loading.value = false;
  }
}

async function loadInstalls() {
  installsLoading.value = true;
  try {
    const result = await fetchConnectorInstalls();
    installs.value = result.items || [];
  } catch (error: any) {
    notice.value = t('加载已安装连接器失败') + '：' + detailOf(error);
  } finally {
    installsLoading.value = false;
  }
}

function detailOf(error: any): string {
  const detail = error?.response?.data?.detail;
  if (Array.isArray(detail)) return detail.join('；');
  return String(detail || error?.message || error);
}

function openInstall(template: ConnectorTemplateDto) {
  installTemplate.value = template;
  installForm.name = localize(template.name);
  installForm.values = {};
  installForm.activate = false;
  template.params.forEach((param) => {
    installForm.values[param.key] = '';
  });
  installVisible.value = true;
}

async function onInstall() {
  if (!installTemplate.value) return;
  const values: Record<string, string> = {};
  Object.entries(installForm.values).forEach(([key, value]) => {
    if (String(value || '').trim()) values[key] = String(value).trim();
  });
  installing.value = true;
  try {
    await installConnectorTemplate(installTemplate.value.id, {
      name: installForm.name.trim() || undefined,
      values,
      activate: installForm.activate,
    });
    message.success(t('连接器已创建'));
    installVisible.value = false;
    await Promise.all([load(), loadInstalls()]);
    tab.value = 'installs';
  } catch (error: any) {
    notice.value = t('创建连接器失败') + '：' + detailOf(error);
  } finally {
    installing.value = false;
  }
}

onMounted(async () => {
  await load();
  await loadInstalls();
});
</script>

<style scoped>
.connector-market {
  padding: 16px 20px 32px;
}
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}
.page-header h1 {
  font-size: 18px;
  font-weight: 600;
}
.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.notice {
  margin-bottom: 12px;
}
.filters {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}
.cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 12px;
}
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.desc {
  margin: 8px 0;
  color: var(--mg-text-2);
  font-size: 13px;
  line-height: 1.5;
}
.meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.count {
  color: var(--mg-text-3);
  font-size: 12px;
}
.inline-hint {
  margin-top: 8px;
}
.card-actions {
  margin-top: 12px;
  display: flex;
  justify-content: flex-end;
}
.param-feedback {
  color: var(--mg-text-3);
  font-size: 12px;
}
.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
</style>
