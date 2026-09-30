<template>
  <div class="tenant-page">
    <n-card class="tenant-card" :bordered="false">
      <div class="page-head">
        <div>
          <h2>{{ t('租户管理') }}</h2>
          <p>{{ t('创建并管理各企业租户，控制其启用、归档与彻底清理。') }}</p>
        </div>
        <n-space :size="10">
          <n-button secondary :loading="loading" @click="loadTenants">{{ t('刷新') }}</n-button>
          <n-button type="primary" @click="openCreate">{{ t('创建租户') }}</n-button>
        </n-space>
      </div>

      <n-space class="filters" :size="12" align="center">
        <n-input
          v-model:value="query.keyword"
          class="keyword-input"
          clearable
          :placeholder="t('搜索租户名或标识')"
          @keydown.enter.prevent="loadTenants"
        />
        <n-select v-model:value="query.status" class="status-select" :options="statusOptions" :placeholder="t('全部状态')" />
        <n-button secondary @click="loadTenants">{{ t('查询') }}</n-button>
      </n-space>

      <n-spin :show="loading">
        <div v-if="!loading && !tenants.length" class="empty-state">
          <div class="empty-icon" aria-hidden="true">+</div>
          <h3>{{ t('还没有租户，立即创建') }}</h3>
          <p>{{ t('还没有任何租户。创建第一个租户后，企业即可登录使用。') }}</p>
          <n-button type="primary" size="large" @click="openCreate">{{ t('创建租户') }}</n-button>
        </div>

        <n-table v-else :bordered="false" size="small" class="tenant-table">
          <thead>
            <tr>
              <th>{{ t('租户名') }}</th>
              <th>{{ t('状态') }}</th>
              <th>{{ t('成员上限') }}</th>
              <th>{{ t('创建时间') }}</th>
              <th>{{ t('操作') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="tenant in tenants" :key="tenant.mainId">
              <td>
                <div class="tenant-name">{{ tenant.name }}</div>
                <div class="tenant-id">{{ tenant.mainId }}</div>
              </td>
              <td>
                <n-tag :type="statusTagType(tenant.status)" size="small" round>{{ statusLabel(tenant.status) }}</n-tag>
              </td>
              <td>{{ memberLimitLabel(tenant) }}</td>
              <td>{{ formatDate(tenant.createdAt) }}</td>
              <td>
                <n-space :size="6">
                  <n-button text type="primary" @click="openDetail(tenant)">{{ t('详情') }}</n-button>
                  <n-button
                    v-if="tenant.status === 'active' || tenant.status === 'disabled'"
                    text
                    type="primary"
                    @click="openEdit(tenant)"
                  >
                    {{ t('编辑租户') }}
                  </n-button>
                  <n-button v-if="tenant.status === 'archived'" text type="primary" @click="openRestore(tenant)">
                    {{ t('恢复') }}
                  </n-button>
                </n-space>
              </td>
            </tr>
          </tbody>
        </n-table>

        <div v-if="total > pageSize" class="pager">
          <n-pagination
            :page="query.page"
            :page-size="pageSize"
            :item-count="total"
            @update:page="handlePageChange"
          />
        </div>
      </n-spin>
    </n-card>

    <n-modal
      v-model:show="createVisible"
      preset="card"
      :title="t('创建租户')"
      style="width: 620px"
      :mask-closable="false"
    >
      <p class="modal-hint">{{ t('仅需填写企业名称与管理员账号密码即可开通；可选配置可展开后填写。') }}</p>
      <TenantCreateForm ref="createFormRef" :submitting="submitting" @submit="submitCreate" @cancel="createVisible = false" />
    </n-modal>

    <n-modal v-model:show="editVisible" preset="card" :title="t('编辑租户')" style="width: 520px">
      <n-form label-placement="top">
        <n-form-item :label="t('租户名')">
          <n-input v-model:value="editForm.name" />
        </n-form-item>
        <n-form-item :label="t('成员上限')">
          <n-input-number v-model:value="editForm.memberLimit" :min="1" :placeholder="t('不限人数')" style="width: 100%" />
        </n-form-item>
        <n-form-item :label="t('状态')">
          <n-radio-group v-model:value="editForm.status">
            <n-space>
              <n-radio value="active">{{ t('活跃') }}</n-radio>
              <n-radio value="disabled">{{ t('已禁用') }}</n-radio>
            </n-space>
          </n-radio-group>
        </n-form-item>
      </n-form>
      <template #footer>
        <n-space justify="end" :size="10">
          <n-button @click="editVisible = false">{{ t('取消') }}</n-button>
          <n-button type="primary" :loading="editing" @click="submitEdit">{{ t('保存') }}</n-button>
        </n-space>
      </template>
    </n-modal>

    <n-modal v-model:show="archiveVisible" preset="card" :title="t('归档租户')" style="width: 480px">
      <n-alert type="warning" :show-icon="true" class="modal-alert">
        {{ t('归档后该租户成员将无法登录，且不计入授权数；数据保留，可随时恢复。') }}
      </n-alert>
      <n-form label-placement="top">
        <n-form-item :label="t('归档原因')">
          <n-input v-model:value="archiveReason" type="textarea" :rows="3" :placeholder="t('可选')" />
        </n-form-item>
      </n-form>
      <template #footer>
        <n-space justify="end" :size="10">
          <n-button @click="archiveVisible = false">{{ t('取消') }}</n-button>
          <n-button type="warning" :loading="archiving" @click="submitArchive">{{ t('确认归档') }}</n-button>
        </n-space>
      </template>
    </n-modal>

    <n-modal v-model:show="restoreVisible" preset="card" :title="t('恢复租户')" style="width: 480px">
      <n-alert type="info" :show-icon="true" class="modal-alert">
        {{ t('恢复后该租户将重新可登录，并重新计入授权数。') }}
      </n-alert>
      <template #footer>
        <n-space justify="end" :size="10">
          <n-button @click="restoreVisible = false">{{ t('取消') }}</n-button>
          <n-button type="primary" :loading="restoring" @click="submitRestore">{{ t('恢复') }}</n-button>
        </n-space>
      </template>
    </n-modal>

    <n-modal v-model:show="purgeVisible" preset="card" :title="t('彻底清理')" style="width: 520px">
      <n-alert type="error" :show-icon="true" class="modal-alert">
        {{ t('彻底清理会永久删除该租户的数据库记录、向量与文件，且不可撤销。') }}
      </n-alert>
      <n-form label-placement="top">
        <n-form-item :label="t('请输入租户名 {name} 以确认', { name: purgeTarget?.name || '' })">
          <n-input v-model:value="purgeConfirmName" :placeholder="purgeTarget?.name || ''" />
        </n-form-item>
      </n-form>
      <template #footer>
        <n-space justify="end" :size="10">
          <n-button @click="purgeVisible = false">{{ t('取消') }}</n-button>
          <n-button type="error" :disabled="!purgeConfirmed" :loading="purging" @click="submitPurge">
            {{ t('彻底清理') }}
          </n-button>
        </n-space>
      </template>
    </n-modal>

    <n-modal
      v-model:show="detailVisible"
      preset="card"
      :title="t('租户详情')"
      style="width: 620px"
    >
      <n-descriptions v-if="detailTenant" :column="1" label-placement="left" bordered size="small">
        <n-descriptions-item :label="t('租户名')">{{ detailTenant.name }}</n-descriptions-item>
        <n-descriptions-item :label="t('租户标识')">{{ detailTenant.mainId }}</n-descriptions-item>
        <n-descriptions-item :label="t('状态')">
          <n-tag :type="statusTagType(detailTenant.status)" size="small" round>{{ statusLabel(detailTenant.status) }}</n-tag>
        </n-descriptions-item>
        <n-descriptions-item :label="t('成员上限')">{{ memberLimitLabel(detailTenant) }}</n-descriptions-item>
        <n-descriptions-item :label="t('管理员账号')">{{ detailTenant.adminUsername }}</n-descriptions-item>
        <n-descriptions-item :label="t('创建时间')">{{ formatDate(detailTenant.createdAt) }}</n-descriptions-item>
        <n-descriptions-item :label="t('创建人')">{{ detailTenant.createdBy || '-' }}</n-descriptions-item>
        <n-descriptions-item v-if="detailTenant.archivedAt" :label="t('已归档')">
          {{ formatDate(detailTenant.archivedAt) }}
          <span v-if="detailTenant.archiveReason">（{{ detailTenant.archiveReason }}）</span>
        </n-descriptions-item>
      </n-descriptions>

      <template #footer>
        <n-space justify="space-between" :size="10">
          <n-space :size="10">
            <n-button
              v-if="detailTenant && (detailTenant.status === 'active' || detailTenant.status === 'disabled')"
              type="error"
              secondary
              @click="openArchiveFromDetail"
            >
              {{ t('归档租户') }}
            </n-button>
            <n-button
              v-if="detailTenant && detailTenant.status === 'archived'"
              type="error"
              secondary
              @click="openPurgeFromDetail"
            >
              {{ t('彻底清理') }}
            </n-button>
          </n-space>
          <n-space :size="10">
            <n-button
              v-if="detailTenant && detailTenant.status !== 'purged'"
              secondary
              @click="openResetFromDetail"
            >
              {{ t('重置密码') }}
            </n-button>
            <n-button @click="detailVisible = false">{{ t('关闭') }}</n-button>
          </n-space>
        </n-space>
      </template>
    </n-modal>

    <n-modal v-model:show="resetVisible" preset="card" :title="t('重置密码')" style="width: 460px">
      <n-form label-placement="top">
        <n-form-item :label="t('新密码')">
          <n-input
            v-model:value="resetPassword"
            type="password"
            show-password-on="click"
            :placeholder="t('至少 6 位')"
          />
        </n-form-item>
      </n-form>
      <template #footer>
        <n-space justify="end" :size="10">
          <n-button @click="resetVisible = false">{{ t('取消') }}</n-button>
          <n-button
            type="primary"
            :disabled="resetPassword.trim().length < 6"
            :loading="resetting"
            @click="submitReset"
          >
            {{ t('确认重置') }}
          </n-button>
        </n-space>
      </template>
    </n-modal>

    <n-modal v-model:show="progressVisible" preset="card" :title="t('清理进度')" style="width: 460px" :mask-closable="false">
      <n-list>
        <n-list-item v-for="item in progressItems" :key="item.key">
          <n-space justify="space-between" align="center" style="width: 100%">
            <span>{{ item.label }}</span>
            <n-tag :type="item.type" size="small" round>{{ item.text }}</n-tag>
          </n-space>
        </n-list-item>
      </n-list>
      <n-alert v-if="progressErrors.length" type="warning" :show-icon="true" class="modal-alert">
        {{ progressErrors.join('；') }}
      </n-alert>
      <template #footer>
        <n-space justify="end">
          <n-button :disabled="purgeStatus === 'running'" @click="closeProgress">{{ t('关闭') }}</n-button>
        </n-space>
      </template>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue';
import { useMessage } from 'naive-ui';
import axios from 'axios';
import TenantCreateForm from '@/components/platform/TenantCreateForm.vue';
import {
  archiveTenant,
  createTenant,
  fetchPurgeStatus,
  fetchTenants,
  purgeTenant,
  resetTenantAdminPassword,
  restoreTenant,
  updateTenant,
  type PlatformTenant,
  type PurgeProgress,
  type TenantCreatePayload,
  type TenantStatus,
} from '@/api/platform';
import { t } from '@/composables/i18n';

const message = useMessage();

const loading = ref(false);
const submitting = ref(false);
const editing = ref(false);
const archiving = ref(false);
const restoring = ref(false);
const purging = ref(false);
const resetting = ref(false);

const tenants = ref<PlatformTenant[]>([]);
const total = ref(0);
const pageSize = 50;

const query = reactive<{ page: number; keyword: string; status: TenantStatus | '' }>({
  page: 1,
  keyword: '',
  status: '',
});

const statusOptions = computed(() => [
  { label: t('全部状态'), value: '' },
  { label: t('活跃'), value: 'active' },
  { label: t('已禁用'), value: 'disabled' },
  { label: t('已归档'), value: 'archived' },
  { label: t('已清理'), value: 'purged' },
]);

const createVisible = ref(false);
const createFormRef = ref<InstanceType<typeof TenantCreateForm> | null>(null);
const editVisible = ref(false);
const archiveVisible = ref(false);
const restoreVisible = ref(false);
const purgeVisible = ref(false);
const detailVisible = ref(false);
const resetVisible = ref(false);
const progressVisible = ref(false);

const editTarget = ref<PlatformTenant | null>(null);
const editForm = reactive<{ name: string; memberLimit: number | null; status: 'active' | 'disabled' }>({
  name: '',
  memberLimit: null,
  status: 'active',
});

const archiveTarget = ref<PlatformTenant | null>(null);
const archiveReason = ref('');
const restoreTarget = ref<PlatformTenant | null>(null);
const purgeTarget = ref<PlatformTenant | null>(null);
const purgeConfirmName = ref('');
const detailTenant = ref<PlatformTenant | null>(null);
const resetPassword = ref('');
const resetTarget = ref<PlatformTenant | null>(null);
const purgeStatus = ref<PurgeProgress['status']>('unknown');
const progress = ref<PurgeProgress | null>(null);
let progressTimer: ReturnType<typeof setTimeout> | null = null;

function parseError(error: unknown, fallback: string) {
  if (axios.isAxiosError(error)) return String(error.response?.data?.detail || error.message || fallback);
  return fallback;
}

function statusLabel(value: TenantStatus) {
  return { active: t('活跃'), disabled: t('已禁用'), archived: t('已归档'), purged: t('已清理') }[value] || value;
}

function statusTagType(value: TenantStatus) {
  return { active: 'success', disabled: 'warning', archived: 'default', purged: 'error' }[value] as
    | 'success'
    | 'warning'
    | 'default'
    | 'error';
}

function memberLimitLabel(tenant: PlatformTenant) {
  return tenant.memberLimit === null || tenant.memberLimit === undefined ? t('不限人数') : String(tenant.memberLimit);
}

function formatDate(value?: string) {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

async function loadTenants() {
  loading.value = true;
  try {
    const data = await fetchTenants({
      page: query.page,
      pageSize,
      keyword: query.keyword.trim(),
      status: query.status,
    });
    tenants.value = data.items || [];
    total.value = data.total || 0;
  } catch (error) {
    message.error(parseError(error, t('加载失败')));
  } finally {
    loading.value = false;
  }
}

function handlePageChange(page: number) {
  query.page = page;
  void loadTenants();
}

function openCreate() {
  createFormRef.value?.reset();
  createVisible.value = true;
}

async function submitCreate(payload: TenantCreatePayload) {
  submitting.value = true;
  try {
    const result = await createTenant(payload);
    createVisible.value = false;
    message.success(`${t('创建成功')}：${result.org_name}`);
    await loadTenants();
  } catch (error) {
    message.error(parseError(error, t('创建租户失败')));
  } finally {
    submitting.value = false;
  }
}

function openEdit(tenant: PlatformTenant) {
  editTarget.value = tenant;
  editForm.name = tenant.name;
  editForm.memberLimit = tenant.memberLimit ?? null;
  editForm.status = tenant.status === 'disabled' ? 'disabled' : 'active';
  editVisible.value = true;
}

async function submitEdit() {
  const target = editTarget.value;
  if (!target) return;
  editing.value = true;
  try {
    await updateTenant(target.mainId, {
      name: editForm.name.trim() || target.name,
      status: editForm.status,
      memberLimit: editForm.memberLimit === null ? 'null' : editForm.memberLimit,
    });
    editVisible.value = false;
    message.success(t('保存成功'));
    await loadTenants();
  } catch (error) {
    message.error(parseError(error, t('保存失败')));
  } finally {
    editing.value = false;
  }
}

function openArchive(tenant: PlatformTenant) {
  archiveTarget.value = tenant;
  archiveReason.value = '';
  archiveVisible.value = true;
}

function openArchiveFromDetail() {
  if (!detailTenant.value) return;
  detailVisible.value = false;
  openArchive(detailTenant.value);
}

async function submitArchive() {
  const target = archiveTarget.value;
  if (!target) return;
  archiving.value = true;
  try {
    await archiveTenant(target.mainId, archiveReason.value.trim());
    archiveVisible.value = false;
    message.success(t('已归档，可随时恢复'));
    await loadTenants();
  } catch (error) {
    message.error(parseError(error, t('归档失败')));
  } finally {
    archiving.value = false;
  }
}

function openRestore(tenant: PlatformTenant) {
  restoreTarget.value = tenant;
  restoreVisible.value = true;
}

async function submitRestore() {
  const target = restoreTarget.value;
  if (!target) return;
  restoring.value = true;
  try {
    await restoreTenant(target.mainId);
    restoreVisible.value = false;
    message.success(t('已恢复'));
    await loadTenants();
  } catch (error) {
    message.error(parseError(error, t('恢复失败')));
  } finally {
    restoring.value = false;
  }
}

function openPurge(tenant: PlatformTenant) {
  if (tenant.status !== 'archived') {
    message.warning(t('仅已归档的租户可以彻底清理'));
    return;
  }
  purgeTarget.value = tenant;
  purgeConfirmName.value = '';
  purgeVisible.value = true;
}

function openPurgeFromDetail() {
  if (!detailTenant.value) return;
  detailVisible.value = false;
  openPurge(detailTenant.value);
}

const purgeConfirmed = computed(() => Boolean(purgeTarget.value) && purgeConfirmName.value === purgeTarget.value?.name);

async function submitPurge() {
  const target = purgeTarget.value;
  if (!target) return;
  if (!purgeConfirmed.value) {
    message.warning(t('名称不匹配，无法清理'));
    return;
  }
  purging.value = true;
  try {
    await purgeTenant(target.mainId, purgeConfirmName.value);
    purgeVisible.value = false;
    message.success(t('清理任务已开始'));
    purgeStatus.value = 'running';
    progress.value = { status: 'running' };
    progressVisible.value = true;
    pollPurgeStatus(target.mainId);
    await loadTenants();
  } catch (error) {
    message.error(parseError(error, t('清理失败')));
  } finally {
    purging.value = false;
  }
}

function pollPurgeStatus(mainId: string) {
  if (progressTimer) clearTimeout(progressTimer);
  progressTimer = setTimeout(async () => {
    try {
      const result = await fetchPurgeStatus(mainId);
      progress.value = result;
      purgeStatus.value = result.status;
      if (result.status === 'running') {
        pollPurgeStatus(mainId);
      } else {
        await loadTenants();
      }
    } catch (error) {
      purgeStatus.value = 'unknown';
      progress.value = { status: 'unknown' };
      console.error(error);
    }
  }, 2000);
}

function closeProgress() {
  if (progressTimer) clearTimeout(progressTimer);
  progressTimer = null;
  progressVisible.value = false;
}

const progressItems = computed(() => {
  const current = progress.value;
  const map: Array<{ key: keyof PurgeProgress; label: string }> = [
    { key: 'mongo', label: t('数据库记录') },
    { key: 'vectors', label: t('向量索引') },
    { key: 'files', label: t('文件存储') },
  ];
  return map.map((item) => {
    const raw = current ? (current[item.key] as string | undefined) : undefined;
    return {
      key: item.key,
      label: item.label,
      text: raw === 'done' ? t('已完成') : raw === 'failed' ? t('失败') : raw === 'running' ? t('进行中') : t('未知'),
      type: raw === 'done' ? 'success' : raw === 'failed' ? 'error' : raw === 'running' ? 'info' : 'default',
    };
  });
});

const progressErrors = computed(() => progress.value?.errors || []);

function openDetail(tenant: PlatformTenant) {
  detailTenant.value = tenant;
  detailVisible.value = true;
}

function openResetFromDetail() {
  if (!detailTenant.value) return;
  resetTarget.value = detailTenant.value;
  resetPassword.value = '';
  detailVisible.value = false;
  resetVisible.value = true;
}

async function submitReset() {
  const target = resetTarget.value;
  if (!target) return;
  if (resetPassword.value.trim().length < 6) {
    message.warning(t('新密码至少 6 位'));
    return;
  }
  resetting.value = true;
  try {
    await resetTenantAdminPassword(target.mainId, resetPassword.value);
    resetVisible.value = false;
    message.success(t('密码已重置'));
  } catch (error) {
    message.error(parseError(error, t('重置密码失败')));
  } finally {
    resetting.value = false;
  }
}

onMounted(loadTenants);
</script>

<style scoped>
.tenant-page {
  padding: 20px;
}

.tenant-card {
  border-radius: 18px;
  box-shadow: 0 18px 48px rgba(27, 55, 116, 0.08);
}

.page-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
}

.page-head h2 {
  margin: 0 0 6px;
  font-size: 22px;
}

.page-head p {
  margin: 0;
  color: #64748b;
  font-size: 13px;
}

.filters {
  margin-bottom: 16px;
}

.keyword-input {
  width: 260px;
}

.status-select {
  width: 150px;
}

.tenant-table {
  margin-top: 4px;
}

.tenant-name {
  font-weight: 700;
  color: #10204a;
}

.tenant-id {
  margin-top: 3px;
  color: #8594ad;
  font-size: 12px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}

.empty-state {
  display: grid;
  justify-items: center;
  gap: 10px;
  padding: 56px 20px;
  text-align: center;
}

.empty-icon {
  display: grid;
  width: 56px;
  height: 56px;
  place-items: center;
  border: 1px dashed #b9c8e4;
  border-radius: 50%;
  color: #3568e8;
  font-size: 26px;
  font-weight: 300;
}

.empty-state h3 {
  margin: 4px 0 0;
  font-size: 18px;
}

.empty-state p {
  max-width: 420px;
  margin: 0 0 8px;
  color: #64748b;
  font-size: 13px;
  line-height: 1.7;
}

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 14px;
}

.modal-hint {
  margin: 0 0 14px;
  color: #64748b;
  font-size: 13px;
  line-height: 1.6;
}

.modal-alert {
  margin-bottom: 16px;
}

@media (max-width: 720px) {
  .page-head {
    flex-direction: column;
  }

  .keyword-input,
  .status-select {
    width: 100%;
  }
}
</style>
