<template>
  <div class="mg-page approval-todos-page">
    <header class="page-head">
      <div class="head-text">
        <h1 class="mg-page-title">{{ t('orchestration.todos.title') }}</h1>
        <p class="mg-page-desc">{{ t('orchestration.todos.subtitle') }}</p>
      </div>
      <n-button quaternary :loading="loading" @click="load">
        <template #icon>
          <n-icon><RefreshOutline /></n-icon>
        </template>
        {{ t('orchestration.todos.refresh') }}
      </n-button>
    </header>

    <n-card :bordered="false" embedded>
      <n-spin :show="loading">
        <n-data-table
          v-if="todos.length"
          :columns="columns"
          :data="todos"
          :bordered="false"
          size="small"
          :paginate-single-page="false"
          :pagination="pagination"
        />
        <n-empty v-else-if="!loading" :description="t('orchestration.todos.empty')" />
      </n-spin>
    </n-card>

    <!-- naive-ui 2.45 的事件名是 positive-click / negative-click（不是 positive/negative）；
         写错只会静默关闭弹层而不执行回调。onPositiveClick 同步返回 false 可保持弹层打开。 -->
    <n-modal
      v-model:show="modalOpen"
      preset="dialog"
      :title="
        modalDecision === 'approve'
          ? t('orchestration.todos.approve_title')
          : t('orchestration.todos.reject_title')
      "
      :positive-text="
        modalDecision === 'approve'
          ? t('orchestration.todos.approve')
          : t('orchestration.todos.reject')
      "
      :negative-text="t('orchestration.todos.cancel')"
      :loading="submitting"
      :positive-button-props="modalDecision === 'reject' ? { type: 'error' } : undefined"
      @positive-click="submit"
      @negative-click="modalOpen = false"
    >
      <p class="todo-context">
        {{
          t('orchestration.todos.modal_context', {
            orchestration: activeTodo?.orchestration_id ?? '--',
            node: activeTodo?.node_id ?? '--',
          })
        }}
      </p>
      <n-input
        v-model:value="reason"
        type="textarea"
        :rows="3"
        :placeholder="
          modalDecision === 'reject'
            ? t('orchestration.todos.reject_reason_required')
            : t('orchestration.todos.reason_optional')
        "
      />
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { h, onMounted, ref } from 'vue'
import {
  NButton,
  NCard,
  NDataTable,
  NEmpty,
  NIcon,
  NInput,
  NModal,
  NSpin,
  NTag,
  useMessage,
  type DataTableColumns,
} from 'naive-ui'
import RefreshOutline from '@vicons/ionicons5/es/RefreshOutline'
import { t } from '../../composables/i18n'
import { formatAppDateTime } from '../../composables/appTimezone'
import {
  decideApproval,
  listApprovalTodos,
  errorMessage,
  type ApprovalDecision,
  type OrchestrationTodo,
} from '../../api/orchestrationRuns'

defineEmits<{ back: [] }>()

const message = useMessage()
const loading = ref(false)
const todos = ref<OrchestrationTodo[]>([])
const modalOpen = ref(false)
const modalDecision = ref<ApprovalDecision>('approve')
const activeTodo = ref<OrchestrationTodo | null>(null)
const reason = ref('')
const submitting = ref(false)

const pagination = { pageSize: 20, showSizePicker: true, pageSizes: [10, 20, 50] }

const formatTime = (value?: string | null) => (value ? formatAppDateTime(value) : '--')

const columns: DataTableColumns<OrchestrationTodo> = [
  {
    title: t('orchestration.todos.column_orchestration'),
    key: 'orchestration_id',
    render: (row) => h('strong', row.orchestration_id),
  },
  {
    title: t('orchestration.todos.column_node'),
    key: 'node_id',
    width: 140,
  },
  {
    title: t('orchestration.todos.column_initiator'),
    key: 'initiator_id',
    width: 140,
  },
  {
    title: t('orchestration.todos.column_prompt'),
    key: 'prompt',
    render: (row) => h('span', { class: 'muted' }, row.rendered || row.prompt || '--'),
  },
  {
    title: t('orchestration.todos.column_deadline'),
    key: 'deadline',
    width: 170,
    render: (row) => formatTime(row.deadline),
  },
  {
    title: t('orchestration.todos.column_actions'),
    key: 'actions',
    width: 180,
    render: (row) => [
      h(
        NButton,
        {
          size: 'small',
          type: 'primary',
          disabled: submitting.value,
          onClick: () => openModal(row, 'approve'),
        },
        { default: () => t('orchestration.todos.approve') }
      ),
      h(
        NButton,
        {
          size: 'small',
          type: 'error',
          ghost: true,
          disabled: submitting.value,
          style: 'margin-left: 8px',
          onClick: () => openModal(row, 'reject'),
        },
        { default: () => t('orchestration.todos.reject') }
      ),
    ],
  },
]

async function load() {
  loading.value = true
  try {
    todos.value = await listApprovalTodos()
  } catch (error: any) {
    message.error(errorMessage(error, t('orchestration.todos.load_failed')))
  } finally {
    loading.value = false
  }
}

function openModal(todo: OrchestrationTodo, decision: ApprovalDecision) {
  activeTodo.value = todo
  modalDecision.value = decision
  reason.value = ''
  modalOpen.value = true
}

/**
 * positive-click 回调。naive-ui 的语义：`onPositiveClick` **同步**返回 false 时
 * 弹层保持打开，返回 Promise/true 则视为已处理并关闭。因此守卫必须是同步函数
 * （async 函数一律返回 Promise，守卫会被绕过），校验通过后才把异步提交接出来。
 */
function submit(): boolean {
  const todo = activeTodo.value
  if (!todo) return false
  // 驳回理由必填：与后端 human_approval.decide 的 403 fail-closed 口径一致，
  // 前端先拦一道，避免提交后才收到错误。
  if (modalDecision.value === 'reject' && !reason.value.trim()) {
    message.warning(t('orchestration.todos.reject_reason_required'))
    return false
  }
  void submitDecision(todo)
  return true
}

async function submitDecision(todo: OrchestrationTodo): Promise<void> {
  submitting.value = true
  try {
    const outcome = await decideApproval(todo.run_id, {
      decision: modalDecision.value,
      reason: reason.value.trim(),
      nodeId: todo.node_id,
    })
    message.success(t('orchestration.todos.decided', { status: outcome.status }))
    modalOpen.value = false
    await load()
  } catch (error: any) {
    // 后端 ApprovalError/RunStoreError 的 detail 已是中文可读串（403/409）。
    message.error(errorMessage(error, t('orchestration.todos.decide_failed')))
  } finally {
    submitting.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.todo-context {
  margin: 0 0 12px;
  font-size: 13px;
  color: var(--n-text-color-3, #6b7280);
}
</style>
