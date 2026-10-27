<script setup lang="ts">
import { computed } from 'vue'
import type { PropType } from 'vue'
import { NInput, NInputNumber, NSelect, NDivider, NTag, NAlert } from 'naive-ui'
import { t } from '../../composables/i18n'
import { declaredMultiAgentMode, type CanvasNode, type MultiAgentMode } from './canvasSchema'

/**
 * 节点属性面板（特性 039 FR-009）：编辑被选中节点的参数。
 *
 * - Skill / 工具数据源由父组件（OrchestrationCanvasPage）通过 props 注入，
 *   数据来自既有的 `api/skills.ts` / `api/tools.ts`（US4）。
 * - 来自手工 YAML 的未知 payload 属性**只读保留**，保存时原样带出（FR-009）。
 * - 编辑实时回写到 `node` 对象（父组件 `applyPatch`），画布同步高亮。
 * - 044 联动：LLM 节点可选 round_robin / debate 多智能体模式（本特性只做 UI）。
 */

const props = defineProps({
  node: { type: Object as PropType<CanvasNode | null>, default: null },
  skillOptions: { type: Array as PropType<Array<{ label: string; value: string }>>, default: () => [] },
  toolOptions: { type: Array as PropType<Array<{ label: string; value: string }>>, default: () => [] },
})
const emit = defineEmits<{ (e: 'patch', patch: Record<string, unknown>): void; (e: 'close'): void }>()

const KNOWN_FIELDS = new Set([
  'id',
  'label',
  'skill',
  'tools',
  'tool',
  'timeout',
  'outputKey',
  'description',
  'conditionExpr',
  'falseBranchReason',
  'mode',
  'multiAgentMode',
  'instances',
  'pro',
  'con',
  'arbiter',
])

/** 当前节点声明的 044 协议（kind 优先，其次 llm 节点上的显式选择）。 */
const declaredMode = computed<MultiAgentMode | undefined>(() =>
  props.node ? declaredMultiAgentMode(props.node) : undefined,
)

const unknownKeys = computed(() => {
  if (!props.node) return []
  return Object.keys(props.node.data).filter((key) => !KNOWN_FIELDS.has(key) && key !== 'unknown')
})

function apply(patch: Record<string, unknown>) {
  emit('patch', patch)
}

const multiAgentOptions: Array<{ label: string; value: MultiAgentMode }> = [
  { label: t('orchestration.prop.round_robin'), value: 'round_robin' },
  { label: t('orchestration.prop.debate'), value: 'debate' },
]
</script>

<template>
  <n-divider title-placement="left">{{ t('orchestration.prop.title') }}</n-divider>

  <div v-if="!node" class="orchestration-panel__empty">
    <p>{{ t('orchestration.empty') }}</p>
  </div>

  <div v-else class="orchestration-panel">
    <div class="row">
      <span class="label">{{ t('orchestration.prop.id') }}</span>
      <n-tag size="small" type="info">{{ node.id }}</n-tag>
    </div>

    <div class="field">
      <span class="label">{{ t('orchestration.prop.label') }}</span>
      <n-input
        :value="node.data.label"
        size="small"
        @update:value="(v: string) => apply({ label: v })"
      />
    </div>

    <!-- LLM / 044 协议节点：Skill 选择（roundRobin、debate 也要基底 Skill） -->
    <template v-if="node.kind === 'llm' || node.kind === 'roundRobin' || node.kind === 'debate'">
      <div class="field">
        <span class="label">{{ t('orchestration.prop.skill') }}</span>
        <n-select
          :value="node.data.skill"
          :options="skillOptions"
          clearable
          size="small"
          placeholder="skill"
          @update:value="(v: string | null) => apply({ skill: v || undefined })"
        />
      </div>
      <div v-if="node.kind === 'llm'" class="field">
        <span class="label">{{ t('orchestration.prop.multi_agent_mode') }}</span>
        <n-select
          :value="node.data.multiAgentMode || ''"
          :options="multiAgentOptions"
          clearable
          size="small"
          placeholder="—"
          @update:value="(v: MultiAgentMode | null) => apply({ multiAgentMode: v || undefined })"
        />
      </div>
    </template>

    <!-- 044 debate：正反方与裁决节点（引擎装载期 fail-closed，缺一不可） -->
    <template v-if="declaredMode === 'debate'">
      <div class="field">
        <span class="label">{{ t('orchestration.prop.debate_pro') }}</span>
        <n-input
          :value="node.data.pro"
          size="small"
          placeholder="node_id"
          @update:value="(v: string) => apply({ pro: v || undefined })"
        />
      </div>
      <div class="field">
        <span class="label">{{ t('orchestration.prop.debate_con') }}</span>
        <n-input
          :value="node.data.con"
          size="small"
          placeholder="node_id"
          @update:value="(v: string) => apply({ con: v || undefined })"
        />
      </div>
      <div class="field">
        <span class="label">{{ t('orchestration.prop.debate_arbiter') }}</span>
        <n-input
          :value="node.data.arbiter"
          size="small"
          placeholder="node_id"
          @update:value="(v: string) => apply({ arbiter: v || undefined })"
        />
      </div>
    </template>

    <!-- 044 round_robin：候选实例首期只读保留（来自手工 YAML，画布暂不提供编辑） -->
    <n-alert
      v-if="declaredMode === 'round_robin' && node.data.instances?.length"
      type="info"
      :bordered="false"
      size="small"
    >
      {{ t('orchestration.prop.round_robin_instances', { count: node.data.instances.length }) }}
    </n-alert>

    <!-- 工具节点：工具选择 -->
    <div v-if="node.kind === 'tool'" class="field">
      <span class="label">{{ t('orchestration.prop.tools') }}</span>
      <n-select
        :value="node.data.tools?.[0]"
        :options="toolOptions"
        clearable
        multiple
        size="small"
        placeholder="tools"
        @update:value="(v: (string | number)[] | null) => apply({ tools: (v || []).map(String) })"
      />
    </div>

    <!-- 条件节点 -->
    <template v-if="node.kind === 'condition'">
      <div class="field">
        <span class="label">{{ t('orchestration.prop.condition_expr') }}</span>
        <n-input
          :value="node.data.conditionExpr"
          size="small"
          type="textarea"
          :autosize="{ minRows: 2, maxRows: 4 }"
          placeholder="completed_children_count < 3"
          @update:value="(v: string) => apply({ conditionExpr: v })"
        />
      </div>
      <div class="field">
        <span class="label">{{ t('orchestration.prop.false_reason') }}</span>
        <n-input
          :value="node.data.falseBranchReason"
          size="small"
          @update:value="(v: string) => apply({ falseBranchReason: v })"
        />
      </div>
    </template>

    <div class="field">
      <span class="label">{{ t('orchestration.prop.output_key') }}</span>
      <n-input
        :value="node.data.outputKey"
        size="small"
        @update:value="(v: string) => apply({ outputKey: v })"
      />
    </div>

    <div class="field">
      <span class="label">{{ t('orchestration.prop.timeout') }}</span>
      <n-input-number
        :value="node.data.timeout ?? null"
        size="small"
        :min="0"
        :show-button="false"
        @update:value="(v: number | null) => apply({ timeout: v ?? undefined })"
      />
    </div>

    <div class="field">
      <span class="label">{{ t('orchestration.prop.description') }}</span>
      <n-input
        :value="node.data.description"
        size="small"
        type="textarea"
        :autosize="{ minRows: 2, maxRows: 4 }"
        @update:value="(v: string) => apply({ description: v })"
      />
    </div>

    <n-alert v-if="unknownKeys.length" type="warning" :bordered="false" size="small">
      {{ t('orchestration.prop.unknown_payload') }}
      <ul class="unknown-keys">
        <li v-for="key in unknownKeys" :key="key"><code>{{ key }}</code></li>
      </ul>
    </n-alert>

    <button class="orchestration-panel__close" type="button" @click="emit('close')">
      {{ t('orchestration.back') }}
    </button>
  </div>
</template>

<style scoped>
.orchestration-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.orchestration-panel__empty {
  color: var(--text-3, #909399);
  font-size: 13px;
}
.row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.label {
  font-size: 12px;
  color: var(--text-2, #606266);
}
.unknown-keys {
  margin: 6px 0 0;
  padding-left: 16px;
  font-size: 12px;
}
.orchestration-panel__close {
  align-self: flex-start;
  margin-top: 4px;
  padding: 4px 10px;
  border: 1px solid var(--border-color, #dcdfe6);
  border-radius: 4px;
  background: transparent;
  cursor: pointer;
}
</style>