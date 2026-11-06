<template>
  <!-- 017 T029 — user「我的记忆」主页面（参考 MySkillsPage.vue / SkillViewTabs.vue 范式）。
       支持双 Tab、搜索、增删改、提升申请、通知提示；不含项目成员编辑（归 049）。
       不可见一律 404：失败统一用 memoryErrorText 显示，不泄露内容（T030）。 -->
  <div class="mg-page memories-page">
    <div class="metrics-row">
      <n-card v-for="item in metrics" :key="item.label" class="metric-card" :bordered="false" size="small">
        <div class="metric-label">{{ item.label }}</div>
        <div class="metric-value" :class="{ danger: item.danger }">{{ item.value }}</div>
        <div class="metric-note">{{ item.note }}</div>
      </n-card>
    </div>

    <n-card class="list-card" :bordered="false" size="large">
      <MemoryViewTabs v-model="activeView" :pending-count="sharedPendingCount" />

      <n-alert v-if="errorMsg" type="warning" :bordered="false" class="hint">{{ errorMsg }}</n-alert>
      <n-alert v-if="activeView === 'shared'" type="info" :bordered="false" class="hint">
        {{ t('「共享给我」= project / department 范围内他人创建的可见记忆；项目成员由「成员」入口管理（049），此处不编辑成员。') }}
      </n-alert>

      <div class="filter-row">
        <n-space align="center" :size="10" wrap>
          <n-input v-model:value="filters.keyword" clearable :placeholder="t('搜索记忆内容')" style="width: 240px" @keyup.enter="load(true)" />
          <n-select v-model:value="filters.scope" clearable :options="filterScopeOptions" :placeholder="t('全部范围')" style="width: 150px" @update:value="load(true)" />
          <n-select v-model:value="filters.status" clearable :options="filterStatusOptions" :placeholder="t('全部状态')" style="width: 140px" @update:value="load(true)" />
          <n-button secondary :loading="loading" @click="load(true)">{{ t('刷新') }}</n-button>
          <n-button v-if="activeView === 'mine'" type="primary" @click="openCreate">{{ t('新建记忆') }}</n-button>
        </n-space>
      </div>

      <n-spin :show="loading">
        <div v-if="visibleRows.length" class="memory-grid">
          <div v-for="row in visibleRows" :key="row.memory_id" class="memory-card">
            <div class="card-head">
              <n-tag size="small" :bordered="false" :type="row.scope === 'department' ? 'warning' : row.scope === 'project' ? 'info' : 'default'">
                {{ scopeLabel(row.scope) }}
              </n-tag>
              <n-tag size="small" :bordered="false" :type="isArchived(row) ? 'default' : 'success'">
                {{ isArchived(row) ? t('已归档') : t('正常') }}
              </n-tag>
              <n-tag v-if="row.resolved_from" size="small" :bordered="false" type="default">{{ row.resolved_from }}</n-tag>
            </div>
            <div class="card-title">{{ row.l0_summary || row.content || t('（无摘要）') }}</div>
            <div class="card-meta">
              <span v-if="row.project_id">{{ t('项目') }}：{{ projectName(row) }}</span>
              <span v-else-if="row.department_id">{{ t('部门') }}：{{ row.department_id }}</span>
              <span>{{ row.created_at || '-' }}</span>
            </div>
            <div class="card-actions">
              <n-button size="tiny" quaternary @click="openDetail(row)">{{ t('详情') }}</n-button>
              <template v-if="activeView === 'mine' && canManage(row)">
                <n-button size="tiny" quaternary @click="openEdit(row)">{{ t('编辑') }}</n-button>
                <n-button size="tiny" quaternary @click="requestPromote(row)">{{ t('申请提升') }}</n-button>
                <n-button size="tiny" quaternary type="error" @click="askDelete(row)">{{ t('删除') }}</n-button>
              </template>
            </div>
          </div>
        </div>
        <n-empty v-else :description="loading ? t('加载中') : t('暂无记忆')" class="empty" />
      </n-spin>

      <div v-if="hasMore" class="load-more">
        <n-button :loading="loading" @click="load(false)">{{ t('加载更多') }}</n-button>
      </div>
    </n-card>

    <MemoryDetailDialog v-model:show="detailVisible" :record="detailRecord" :projects="projects" />

    <n-modal :show="editVisible" preset="card" :title="editingId ? t('编辑记忆') : t('新建记忆')" style="width: 520px" :bordered="false" @update:show="editVisible = $event">
      <div class="field">
        <label class="field-label">{{ t('内容') }} <span class="required">*</span></label>
        <n-input v-model:value="form.content" type="textarea" :rows="4" :placeholder="t('记忆正文，服务端据此生成 L0/L1/L2 分层')" />
      </div>
      <div class="field">
        <label class="field-label">{{ t('范围（由服务端解析最终归属）') }}</label>
        <n-select v-model:value="form.scope" :options="formScopeOptions" />
      </div>
      <div v-if="form.scope === 'project'" class="field">
        <label class="field-label">{{ t('项目') }}</label>
        <n-select v-model:value="form.project_id" clearable :options="projectOptions" :placeholder="t('选择项目（default 不可承载项目记忆）')" />
        <n-alert v-if="isDefaultProject(form.project_id)" type="warning" :bordered="false" class="inline-alert">
          {{ t('project_id=\"default\" 不可承载项目记忆，请改选具体项目。') }}
        </n-alert>
      </div>
      <div v-if="form.scope === 'department'" class="field">
        <label class="field-label">{{ t('部门') }}</label>
        <n-select v-model:value="form.department_id" clearable :options="departmentOptions" :placeholder="t('选择可见部门')" />
      </div>
      <div class="field">
        <label class="field-label">L0 · {{ t('摘要（可选，服务端可回填）') }}</label>
        <n-input v-model:value="form.l0_summary" :placeholder="t('留空由服务端生成')" />
      </div>
      <div class="field">
        <label class="field-label">L1 · {{ t('概览（可选）') }}</label>
        <n-input v-model:value="form.l1_overview" type="textarea" :rows="2" :placeholder="t('留空由服务端生成')" />
      </div>
      <n-alert type="info" :bordered="false" class="hint">
        {{ t('project_owner_id 由服务端解析，客户端传值会被忽略；范围仅 personal / project / department。') }}
      </n-alert>
      <template #footer>
        <n-space justify="end">
          <n-button @click="editVisible = false">{{ t('取消') }}</n-button>
          <n-button type="primary" :loading="saving" :disabled="isDefaultProject(form.project_id) && form.scope === 'project'" @click="saveEdit">{{ t('保存') }}</n-button>
        </n-space>
      </template>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import {
  NAlert, NButton, NCard, NEmpty, NInput, NModal, NSelect, NSpace, NSpin, NTag,
  useDialog, useMessage, useNotification,
} from 'naive-ui'
import { t } from '../composables/i18n'
import MemoryViewTabs from './MemoryViewTabs.vue'
import MemoryDetailDialog from './MemoryDetailDialog.vue'
import {
  MEMORY_SCOPES,
  isDefaultProject,
  type CreateMemoryPayload,
  type MemoryDepartmentNode,
  type MemoryItem,
  type MemoryProjectView,
  type MemoryScope,
  type MemoryStatus,
  listMyMemories,
  createMemory,
  updateMemory,
  deleteMemory,
  promoteMemory,
  listMemoryProjects,
  listMemoryDepartments,
  resolveProjectName,
  memoryErrorText,
  normalizeMemoryError,
} from '../api/memories'

// App.vue 传入当前用户 id，用于区分「我的」与「共享给我」（§7.3）。
const props = defineProps<{ userId?: string | null }>()

const message = useMessage()
const dialog = useDialog()
const notification = useNotification()

const loading = ref(false)
const saving = ref(false)
const errorMsg = ref('')
const all = ref<MemoryItem[]>([])
const cursor = ref<string | undefined>(undefined)
const hasMore = ref(false)
const projects = ref<MemoryProjectView[]>([])
const departments = ref<MemoryDepartmentNode[]>([])

const activeView = ref<'mine' | 'shared'>('mine')
const filters = reactive<{ keyword: string; scope: MemoryScope | ''; status: MemoryStatus | '' }>({ keyword: '', scope: '', status: '' })

const detailVisible = ref(false)
const detailRecord = ref<MemoryItem | null>(null)

const editVisible = ref(false)
const editingId = ref<string | null>(null)
const form = reactive<CreateMemoryPayload>({ content: '', scope: 'personal', project_id: '', department_id: '', l0_summary: '', l1_overview: '' })

const filterScopeOptions = [
  { label: t('全部范围'), value: '' as const },
  ...MEMORY_SCOPES.map((value) => ({ label: scopeLabel(value), value })),
]
const formScopeOptions = MEMORY_SCOPES.map((value) => ({ label: scopeLabel(value), value }))
const filterStatusOptions = [
  { label: t('全部状态'), value: '' as const },
  { label: t('正常'), value: 'active' as const },
  { label: t('已归档'), value: 'archived' as const },
]
const projectOptions = computed(() => projects.value.filter((p) => !isDefaultProject(p.id)).map((p) => ({ label: p.title || p.id, value: p.id })))
const departmentOptions = computed(() => departments.value.map((d) => ({ label: d.name || d.id, value: d.id })))

function scopeLabel(scope: MemoryScope | string): string {
  return ({ personal: t('个人'), project: t('项目'), department: t('部门') } as Record<string, string>)[scope] || scope
}
function isArchived(row: MemoryItem): boolean {
  return Boolean(row.archived) || row.status === 'archived'
}
function canManage(_row: MemoryItem): boolean {
  // 仅「我的」可增删改/提升；服务端仍会做 owner 校验（§7.3），前端只做 UI 收敛。
  return true
}
function projectName(row: MemoryItem): string {
  return resolveProjectName(projects.value, row.project_id, row.project_owner_id)
}

const mine = computed(() => all.value.filter((m) => !props.userId || m.owner_id === props.userId || m.scope === 'personal'))
const shared = computed(() => all.value.filter((m) => Boolean(props.userId) && m.owner_id !== props.userId && m.scope !== 'personal'))
const sharedPendingCount = computed(() => shared.value.length)

function matchKeyword(row: MemoryItem, keyword: string): boolean {
  const q = keyword.trim().toLowerCase()
  if (!q) return true
  return [row.content, row.l0_summary, row.l1_overview, row.project_id, row.department_id]
    .some((v) => String(v || '').toLowerCase().includes(q))
}
const visibleRows = computed(() => {
  const base = activeView.value === 'mine' ? mine.value : shared.value
  return base.filter((row) => matchKeyword(row, filters.keyword))
})

function isThisMonth(value?: string): boolean {
  if (!value) return false
  const d = new Date(value)
  const now = new Date()
  return d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth()
}
function nearDecay(row: MemoryItem): boolean {
  // 近似：最近命中超过 23 天未更新，接近 §9.5 默认 30 天衰减窗口。
  const ref = row.last_accessed_at || row.created_at
  if (!ref) return false
  return Date.now() - new Date(ref).getTime() > 23 * 24 * 3600 * 1000
}
const metrics = computed(() => [
  { label: t('我的记忆'), value: mine.value.length, note: t('个人 + 我创建的共享范围') },
  { label: t('共享给我'), value: shared.value.length, note: t('project / department 他人创建'), danger: false },
  { label: t('本月沉淀'), value: all.value.filter((m) => m.source_session_id && isThisMonth(m.created_at)).length, note: t('会话自动沉淀') },
  { label: t('即将衰减'), value: all.value.filter(nearDecay).length, note: t('近 23 天未命中（近似）'), danger: true },
])

let notified = false
async function load(reset = true) {
  loading.value = true
  errorMsg.value = ''
  try {
    const [res] = await Promise.all([
      listMyMemories({
        limit: 30,
        cursor: reset ? undefined : cursor.value,
        scope: filters.scope,
        status: filters.status,
      }),
      // 项目/部门列表只随首次加载取一次（049 只读端点，用于消歧与筛选）。
      reset && projects.value.length === 0 ? loadAux() : Promise.resolve(),
    ])
    all.value = reset ? res.items : [...all.value, ...res.items]
    cursor.value = res.next_cursor
    hasMore.value = Boolean(res.next_cursor)
    if (!notified) {
      notified = true
      if (shared.value.length) notification.info({ title: t('共享记忆'), content: t('有 {count} 条共享给你的记忆', { count: shared.value.length }), duration: 3000 })
      const decay = all.value.filter(nearDecay).length
      if (decay) notification.warning({ title: t('即将衰减'), content: t('有 {count} 条记忆接近衰减窗口', { count: decay }), duration: 3000 })
    }
  } catch (error: any) {
    const e = normalizeMemoryError(error)
    errorMsg.value = e.notFound ? memoryErrorText(error) : memoryErrorText(error, t('加载失败'))
    if (reset) { all.value = []; hasMore.value = false }
  } finally { loading.value = false }
}
async function loadAux() {
  try {
    const [p, d] = await Promise.all([listMemoryProjects(), listMemoryDepartments()])
    projects.value = p
    departments.value = d
  } catch { /* 只读辅助数据失败不阻断主列表（404 不泄露内容） */ }
}
onMounted(() => load(true))

function openDetail(row: MemoryItem) { detailRecord.value = row; detailVisible.value = true }

function openCreate() {
  editingId.value = null
  Object.assign(form, { content: '', scope: 'personal', project_id: '', department_id: '', l0_summary: '', l1_overview: '' })
  editVisible.value = true
}
function openEdit(row: MemoryItem) {
  editingId.value = row.memory_id
  Object.assign(form, {
    content: row.content || '', scope: row.scope, project_id: row.project_id || '',
    department_id: row.department_id || '', l0_summary: row.l0_summary || '', l1_overview: row.l1_overview || '',
  })
  editVisible.value = true
}
async function saveEdit() {
  if (!form.content.trim()) { message.warning(t('请填写记忆内容')); return }
  if (form.scope === 'project' && isDefaultProject(form.project_id)) {
    message.warning(t('project_id=\"default\" 不可承载项目记忆')); return
  }
  saving.value = true
  try {
    const payload: CreateMemoryPayload = {
      content: form.content.trim(),
      scope: form.scope,
      project_id: form.scope === 'project' ? form.project_id : undefined,
      department_id: form.scope === 'department' ? form.department_id : undefined,
      l0_summary: form.l0_summary || undefined,
      l1_overview: form.l1_overview || undefined,
    }
    if (editingId.value) await updateMemory(editingId.value, payload)
    else await createMemory(payload)
    // TODO(backend)：通用编辑端点 PATCH /api/v1/memories/{id} 待后端提供/确认（见 api/memories.ts）。
    notification.success({ title: t('记忆已保存'), content: t('范围由服务端解析并回显 actual_scope / resolved_from'), duration: 2500 })
    editVisible.value = false
    await load(true)
  } catch (error: any) {
    message.error(memoryErrorText(error, t('保存失败')))
  } finally { saving.value = false }
}

function askDelete(row: MemoryItem) {
  dialog.warning({
    title: t('删除记忆'),
    content: t('仅可删除自己的记忆，删除后不可恢复。确认删除？'),
    positiveText: t('删除'),
    negativeText: t('取消'),
    onPositiveClick: async () => {
      try {
        await deleteMemory(row.memory_id)
        notification.success({ title: t('已删除'), duration: 2000 })
        await load(true)
      } catch (error: any) { message.error(memoryErrorText(error, t('删除失败'))) }
    },
  })
}

async function requestPromote(row: MemoryItem) {
  const dept = row.department_id || departmentOptions.value[0]?.value || ''
  if (!dept) { message.warning(t('请先选择目标部门（提升为 department 级）')); return }
  try {
    // §9.1 PATCH .../promote；普通用户的提升申请由服务端按角色落审批状态机（§7.2 / T035）。
    await promoteMemory(row.memory_id, { target_scope: 'department', department_id: dept })
    notification.success({ title: t('提升申请已提交'), content: t('等待管理员审批，落 feature=\"017\" memory.promoted 审计'), duration: 3000 })
    await load(true)
  } catch (error: any) { message.error(memoryErrorText(error, t('提交失败'))) }
}
</script>

<style scoped>
.memories-page { display: grid; gap: 16px; padding: 20px; height: 100%; min-height: 0; overflow: auto; box-sizing: border-box; }
.metrics-row { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; }
.metric-card { border-radius: 10px; }
.metric-label { color: var(--mg-text-2); font-size: 13px; }
.metric-value { color: var(--mg-text-1); font-size: 26px; font-weight: 700; line-height: 1.3; }
.metric-value.danger { color: var(--mg-danger-text); }
.metric-note { color: var(--mg-text-2); font-size: 12px; }
.list-card { border-radius: 10px; min-width: 0; }
.hint { margin-bottom: 12px; }
.filter-row { margin-bottom: 14px; }
.memory-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 12px; }
.memory-card { display: grid; gap: 8px; padding: 14px; border: 1px solid var(--mg-border); border-radius: 10px; background: var(--mg-bg-surface); }
.card-head { display: flex; gap: 6px; flex-wrap: wrap; }
.card-title { color: var(--mg-text-1); font-size: 14px; line-height: 1.5; white-space: pre-wrap; overflow-wrap: anywhere; }
.card-meta { display: flex; flex-wrap: wrap; gap: 10px; color: var(--mg-text-2); font-size: 12px; }
.card-actions { display: flex; flex-wrap: wrap; gap: 2px; border-top: 1px solid var(--mg-border); padding-top: 8px; }
.empty { padding: 40px 0; }
.load-more { display: flex; justify-content: center; padding-top: 14px; }
.field { margin-bottom: 12px; }
.field-label { display: block; margin-bottom: 6px; font-size: 13px; color: var(--mg-text-2); }
.required { color: var(--mg-danger-text); }
.inline-alert { margin-top: 8px; }
@media (max-width: 900px) { .metrics-row { grid-template-columns: repeat(2, 1fr); } }
</style>
