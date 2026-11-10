<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { NModal, NButton, NInput, NRadioGroup, NRadio, useMessage } from 'naive-ui'
import {
  listProjectDepartments,
  listProjectMemberCandidates,
  type ProjectDepartmentNode,
  type ProjectMemberCandidate,
} from '../../api/sessions'
import { t } from '../../composables/i18n'

/**
 * 050 转人工节点：审批人选择弹窗（单选）。
 *
 * 参考「项目>>成员」(MemberPicker) 的同一数据层——本租户部门树
 * (listProjectDepartments) + end_users 候选 (listProjectMemberCandidates，按部门
 * 子树过滤 + 关键字搜索)，但改为「单选一个 user_id」用于审批人，不再走项目成员
 * 保存逻辑。鉴权 token 取自 localStorage('auth_token')，与 App.vue 写入口径一致。
 *
 * emit select 携带 { id, name }；调用方只把 id 写回 node.data.approver，name 仅 UI 态。
 */
const props = defineProps<{
  show: boolean
  /** 已选审批人 id（来自 node.data.approver），打开时用于预选。 */
  initialApproverId?: string | null
}>()

const emit = defineEmits<{
  (e: 'update:show', value: boolean): void
  (e: 'select', payload: { id: string; name: string }): void
}>()

const message = useMessage()

function authToken(): string | null {
  return localStorage.getItem('auth_token') || null
}

const departments = ref<ProjectDepartmentNode[]>([])
const departmentId = ref('')
const keyword = ref('')
const candidates = ref<ProjectMemberCandidate[]>([])
const loading = ref(false)
const selectedId = ref<string>('')
const selectedName = ref<string>('')

const departmentRows = computed(() => [
  { id: '', name: t('orchestration.prop.approver_all_departments'), depth: 0 },
  ...departments.value.map((item) => ({ id: item.id, name: item.name, depth: item.depth })),
])

function close(): void {
  emit('update:show', false)
}

async function loadDepartments(): Promise<void> {
  try {
    departments.value = await listProjectDepartments(authToken())
  } catch {
    departments.value = []
    message.error(t('orchestration.prop.approver_dept_load_failed'))
  }
}

async function loadCandidates(): Promise<void> {
  loading.value = true
  try {
    candidates.value = await listProjectMemberCandidates(departmentId.value, keyword.value, authToken())
  } catch {
    candidates.value = []
    message.error(t('orchestration.prop.approver_user_load_failed'))
  } finally {
    loading.value = false
  }
}

watch(
  () => props.show,
  async (open) => {
    if (!open) return
    selectedId.value = props.initialApproverId || ''
    selectedName.value = ''
    departmentId.value = ''
    keyword.value = ''
    await Promise.all([loadDepartments(), loadCandidates()])
  },
  { immediate: false },
)

watch(departmentId, () => {
  void loadCandidates()
})

function onPick(id: string): void {
  const hit = candidates.value.find((item) => item.id === id)
  selectedId.value = id
  selectedName.value = hit?.name || hit?.loginName || id
}

function confirm(): void {
  if (!selectedId.value) return
  emit('select', { id: selectedId.value, name: selectedName.value || selectedId.value })
  close()
}
</script>

<template>
  <NModal
    :show="show"
    preset="card"
    :title="t('orchestration.prop.approver_picker_title')"
    class="w-[720px] max-w-[92vw]"
    :bordered="false"
    @update:show="close"
  >
    <div class="flex h-[420px] gap-4">
      <aside class="w-[180px] shrink-0 overflow-y-auto rounded-lg border border-gray-200 p-1.5">
        <button
          v-for="row in departmentRows"
          :key="row.id || 'all'"
          type="button"
          class="flex w-full items-center rounded-md px-2 py-1.5 text-left text-[13px] transition-colors"
          :class="
            departmentId === row.id
              ? 'bg-blue-50 font-medium text-blue-700'
              : 'text-gray-600 hover:bg-gray-100'
          "
          :style="{ paddingLeft: `${8 + row.depth * 12}px` }"
          @click="departmentId = row.id"
        >
          <span class="truncate">{{ row.name }}</span>
        </button>
        <p v-if="departments.length === 0" class="px-2 py-1.5 text-[12px] text-gray-400">
          {{ t('orchestration.prop.approver_no_dept') }}
        </p>
      </aside>
      <section class="flex min-w-0 flex-1 flex-col">
        <NInput
          v-model:value="keyword"
          size="small"
          clearable
          :placeholder="t('orchestration.prop.approver_search_placeholder')"
          @keyup.enter="loadCandidates"
          @clear="loadCandidates"
        />
        <div class="mt-2 min-h-0 flex-1 overflow-y-auto rounded-lg border border-gray-200">
          <p v-if="loading" class="px-3 py-4 text-[12px] text-gray-400">
            {{ t('orchestration.prop.approver_loading') }}
          </p>
          <template v-else>
            <p v-if="candidates.length === 0" class="px-3 py-4 text-[12px] text-gray-400">
              {{ t('orchestration.prop.approver_no_user') }}
            </p>
            <NRadioGroup
              :value="selectedId"
              @update:value="(v: string) => onPick(v)"
            >
              <label
                v-for="item in candidates"
                :key="item.id"
                class="flex cursor-pointer items-center gap-2.5 border-b border-gray-50 px-3 py-2 last:border-b-0 hover:bg-gray-50"
              >
                <NRadio :value="item.id" />
                <span class="min-w-0 flex-1 truncate text-[13px] text-gray-700">
                  {{ item.name || item.loginName || item.id.slice(0, 8) }}
                </span>
                <span class="shrink-0 text-[11px] text-gray-400">{{ item.departmentName }}</span>
              </label>
            </NRadioGroup>
          </template>
        </div>
        <div class="mt-2 flex items-center gap-2 text-[12px] text-gray-500">
          <span>{{ t('orchestration.prop.approver_selected') }}：</span>
          <span class="font-medium text-blue-700">
            {{ selectedName || selectedId || t('orchestration.prop.approver_none') }}
          </span>
        </div>
      </section>
    </div>
    <template #footer>
      <div class="flex justify-end gap-2">
        <NButton size="small" @click="close">{{ t('orchestration.prop.approver_cancel') }}</NButton>
        <NButton size="small" type="primary" :disabled="!selectedId" @click="confirm">
          {{ t('orchestration.prop.approver_confirm') }}
        </NButton>
      </div>
    </template>
  </NModal>
</template>
