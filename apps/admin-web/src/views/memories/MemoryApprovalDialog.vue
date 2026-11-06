<script setup lang="ts">
/**
 * 017 T026 — admin 范围提升审批弹层（参考 PortalApprovalPage.vue 的 reason 状态机弹层）。
 * §9.1 promote：target_scope=department + department_id，后端落 feature="017"
 * memory.promoted 审计（§9.4），前端只调用约定端点，不重写审计桥。
 */
import { ref, watch } from 'vue';
import { t } from '@/composables/i18n';
import { useMessage } from 'naive-ui';
import {
  type MemoryItem,
  submitMemoryApproval,
  memoryErrorText,
} from '@/api/memories';

const props = defineProps<{ show: boolean; record: MemoryItem | null }>();
const emit = defineEmits<{ 'update:show': [value: boolean]; submitted: [] }>();
const message = useMessage();

const departmentId = ref('');
const reason = ref('');
const submitting = ref(false);

watch(() => props.show, (show) => {
  if (show) { departmentId.value = ''; reason.value = ''; }
});

function close() { emit('update:show', false); }

async function submit() {
  if (!props.record) return;
  if (!departmentId.value.trim()) { message.warning(t('请填写目标部门 ID')); return; }
  submitting.value = true;
  try {
    await submitMemoryApproval({
      memory_id: props.record.memory_id,
      target_scope: 'department',
      department_id: departmentId.value.trim(),
      reason: reason.value.trim(),
    });
    message.success(t('提升审批已提交'));
    emit('submitted');
    close();
  } catch (error: any) {
    // TODO(backend): /api/v1/memories/admin/approvals 待后端提供；404 不泄露内容。
    message.error(memoryErrorText(error, t('提交失败')));
  } finally { submitting.value = false; }
}
</script>

<template>
  <n-modal :show="show" preset="card" :title="t('范围提升审批')" style="width: 480px" :bordered="false" @update:show="emit('update:show', $event)">
    <n-descriptions :column="1" label-placement="left" size="small" bordered>
      <n-descriptions-item :label="t('记忆 ID')">{{ record?.memory_id || '-' }}</n-descriptions-item>
      <n-descriptions-item :label="t('当前范围')">{{ record?.scope || '-' }}</n-descriptions-item>
      <n-descriptions-item :label="t('目标范围')">
        <n-tag size="small" :bordered="false" type="warning">{{ t('部门') }} (department)</n-tag>
      </n-descriptions-item>
    </n-descriptions>

    <div class="form-row">
      <label class="form-label">{{ t('目标部门 ID') }} <span class="required">*</span></label>
      <n-input v-model:value="departmentId" :placeholder="t('提升目标部门，须在可见集合内')" />
    </div>
    <div class="form-row">
      <label class="form-label">{{ t('审批理由') }}</label>
      <n-input v-model:value="reason" type="textarea" :rows="3" :placeholder="t('选填，记录提升依据')" />
    </div>
    <n-alert type="info" :bordered="false" class="hint">
      {{ t('提升将落 feature=\"017\" memory.promoted 审计；普通用户的提升申请由服务端按角色走审批状态机。') }}
    </n-alert>

    <template #footer>
      <n-space justify="end">
        <n-button @click="close">{{ t('取消') }}</n-button>
        <n-button type="primary" :loading="submitting" @click="submit">{{ t('提交审批') }}</n-button>
      </n-space>
    </template>
  </n-modal>
</template>

<style scoped>
.form-row { margin-top: 16px; }
.form-label { display: block; margin-bottom: 6px; font-size: 13px; color: var(--mg-text-2); }
.required { color: var(--mg-danger-text); }
.hint { margin-top: 16px; }
</style>
