<script setup lang="ts">
import { t } from '../../composables/i18n'
import { computed, ref, watch } from 'vue'
import { NButton, NCheckbox, NInput, NModal, useMessage } from 'naive-ui'
import {
  listProjectDepartments,
  listProjectMemberCandidates,
  updateDesktopProjectMembers,
  type ProjectDepartmentNode,
  type ProjectMemberCandidate,
} from '../../api/sessions'

/**
 * 049-project-members US1：项目成员选择弹窗。
 *
 * 左侧部门列表（本租户 active 部门，按 depth 缩进）→ 右侧成员候选（end_users，
 * 按部门子树过滤 + 关键字搜索，多选）→ 已选 chip → 保存（PATCH member_user_ids）。
 * 仅项目创建者（props.creatorUserId === props.currentUserId）可编辑。
 */
const props = defineProps<{
  show: boolean
  authToken?: string | null
  projectId: string
  projectTitle: string
  currentUserId: string
  creatorUserId: string
  initialMembers: string[]
}>()

const emit = defineEmits<{
  (e: 'update:show', value: boolean): void
  (e: 'saved', members: string[]): void
}>()

const message = useMessage()
const readonly = computed(() => !props.currentUserId || props.creatorUserId !== props.currentUserId)

const departments = ref<ProjectDepartmentNode[]>([])
const departmentsLoading = ref(false)
/** 空字符串表示「全部部门」。 */
const departmentId = ref('')
const keyword = ref('')
const candidates = ref<ProjectMemberCandidate[]>([])
const candidatesLoading = ref(false)
const selected = ref<string[]>([])
const saving = ref(false)

/** 已选成员的展示信息（含跨部门成员）。 */
const selectedInfo = ref<Record<string, ProjectMemberCandidate>>({})

const departmentRows = computed(() => [
  { id: '', name: '全部部门', depth: 0 },
  ...departments.value.map(item => ({ id: item.id, name: item.name, depth: item.depth })),
])

function close(): void {
  emit('update:show', false)
}

/** 接口失败不再静默伪装成「暂无数据」：控制台留栈、界面给可见提示。 */
function reportLoadError(scope: string, err: unknown): void {
  const status = (err as { response?: { status?: number } })?.response?.status
  console.error(`[MemberPicker] ${scope}加载失败`, err)
  message.error(`${scope}加载失败${status ? `（HTTP ${status}）` : ''}，请稍后重试`)
}

async function loadDepartments(): Promise<void> {
  if (!props.authToken) return
  departmentsLoading.value = true
  try {
    departments.value = await listProjectDepartments(props.authToken)
  } catch (err) {
    departments.value = []
    reportLoadError('部门列表', err)
  } finally {
    departmentsLoading.value = false
  }
}

async function loadCandidates(): Promise<void> {
  if (!props.authToken) return
  candidatesLoading.value = true
  try {
    const items = await listProjectMemberCandidates(departmentId.value, keyword.value, props.authToken)
    candidates.value = items
    for (const item of items) {
      if (selected.value.includes(item.id)) selectedInfo.value = { ...selectedInfo.value, [item.id]: item }
    }
  } catch (err) {
    candidates.value = []
    reportLoadError('成员列表', err)
  } finally {
    candidatesLoading.value = false
  }
}

watch(() => props.show, async (open) => {
  if (!open) return
  departmentId.value = ''
  keyword.value = ''
  selected.value = [...(props.initialMembers || [])]
  selectedInfo.value = {}
  await Promise.all([loadDepartments(), loadCandidates()])
}, { immediate: false })

watch(departmentId, () => { void loadCandidates() })

function selectDepartment(id: string): void {
  departmentId.value = id
}

function toggleMember(id: string): void {
  if (readonly.value) return
  if (selected.value.includes(id)) {
    selected.value = selected.value.filter(item => item !== id)
  } else {
    selected.value = [...selected.value, id]
    const hit = candidates.value.find(item => item.id === id)
    if (hit) selectedInfo.value = { ...selectedInfo.value, [id]: hit }
  }
}

async function save(): Promise<void> {
  if (readonly.value || saving.value || !props.authToken) return
  saving.value = true
  try {
    const project = await updateDesktopProjectMembers(props.projectId, selected.value, props.authToken)
    emit('saved', project?.member_user_ids || selected.value)
    message.success('项目成员已更新')
    close()
  } catch (err) {
    message.error(String(err))
  } finally {
    saving.value = false
  }
}

function memberLabel(id: string): string {
  return selectedInfo.value[id]?.name || id.slice(0, 8)
}
</script>

<template>
  <NModal
    :show="show"
    preset="card"
    :title="`成员 · ${projectTitle}`"
    class="w-[720px] max-w-[92vw]"
    :bordered="false"
    @update:show="close"
  >
    <p v-if="readonly" class="mb-3 rounded-lg bg-amber-50 px-3 py-2 text-[12px] text-amber-700">{{ t('只有项目创建者可以管理成员，你可以查看当前成员。') }}</p>
    <div class="flex h-[420px] gap-4">
      <aside class="w-[180px] shrink-0 overflow-y-auto rounded-lg border border-gray-200 p-1.5">
        <button
          v-for="row in departmentRows"
          :key="row.id || 'all'"
          type="button"
          class="flex w-full items-center rounded-md px-2 py-1.5 text-left text-[13px] transition-colors"
          :class="departmentId === row.id ? 'bg-blue-50 font-medium text-blue-700' : 'text-gray-600 hover:bg-gray-100'"
          :style="{ paddingLeft: `${8 + row.depth * 12}px` }"
          @click="selectDepartment(row.id)"
        >
          <span class="truncate">{{ row.name }}</span>
        </button>
        <p v-if="!departmentsLoading && departments.length === 0" class="px-2 py-1.5 text-[12px] text-gray-400">{{ t('暂无部门数据') }}</p>
      </aside>
      <section class="flex min-w-0 flex-1 flex-col">
        <NInput v-model:value="keyword" size="small" clearable :placeholder="t('搜索姓名 / 账号 / 手机号')" @keyup.enter="loadCandidates" @clear="loadCandidates" />
        <div class="mt-2 min-h-0 flex-1 overflow-y-auto rounded-lg border border-gray-200">
          <p v-if="candidatesLoading" class="px-3 py-4 text-[12px] text-gray-400">{{ t('加载中…') }}</p>
          <p v-else-if="candidates.length === 0" class="px-3 py-4 text-[12px] text-gray-400">{{ t('该部门下没有可选成员') }}</p>
          <label
            v-for="item in candidates"
            :key="item.id"
            class="flex cursor-pointer items-center gap-2.5 border-b border-gray-50 px-3 py-2 last:border-b-0 hover:bg-gray-50"
          >
            <NCheckbox
              :checked="selected.includes(item.id)"
              :disabled="readonly"
              @update:checked="toggleMember(item.id)"
            />
            <span class="min-w-0 flex-1 truncate text-[13px] text-gray-700">{{ item.name || item.loginName || item.id.slice(0, 8) }}</span>
            <span class="shrink-0 text-[11px] text-gray-400">{{ item.departmentName }}</span>
          </label>
        </div>
        <div class="mt-2 flex flex-wrap items-center gap-1.5">
          <span class="text-[12px] text-gray-500">已选 {{ selected.length }} 人</span>
          <span
            v-for="id in selected"
            :key="id"
            class="inline-flex items-center gap-1 rounded-full bg-blue-50 px-2 py-0.5 text-[12px] text-blue-700"
          >
            {{ memberLabel(id) }}
            <button v-if="!readonly" type="button" class="text-blue-400 hover:text-blue-700" @click="toggleMember(id)">×</button>
          </span>
        </div>
      </section>
    </div>
    <template #footer>
      <div class="flex justify-end gap-2">
        <NButton size="small" @click="close">{{ readonly ? '关闭' : '取消' }}</NButton>
        <NButton v-if="!readonly" size="small" type="primary" :loading="saving" @click="save">{{ t('保存') }}</NButton>
      </div>
    </template>
  </NModal>
</template>
