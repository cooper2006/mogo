<template>
  <div class="portal-detail">
    <n-spin :show="loading">
      <n-alert v-if="error" type="error" :bordered="false">{{ error }}</n-alert>

      <template v-else-if="detail">
        <n-space vertical :size="12">
          <div class="detail-head">
            <div>
              <h3>{{ detail.item.name }}</h3>
              <p class="muted">{{ detail.item.description || '暂无描述' }}</p>
            </div>
            <n-tag :type="detail.granted ? 'success' : 'default'" :bordered="false">
              {{ detail.granted ? '已开通' : '未开通' }}
            </n-tag>
          </div>

          <n-space :size="8" wrap>
            <n-tag size="small" :bordered="false">{{ assetTypeLabel }}</n-tag>
            <n-tag size="small" :bordered="false">{{ detail.item.category || '未分类' }}</n-tag>
            <n-tag v-if="detail.item.rating" size="small" type="info" :bordered="false">
              信任评级 {{ detail.item.rating.level }}
            </n-tag>
            <n-tag v-if="detail.item.is_low_quality" size="small" type="warning" :bordered="false">低质量提示</n-tag>
            <n-tag v-for="tag in detail.item.tags" :key="tag" size="small" :bordered="false">{{ tag }}</n-tag>
          </n-space>

          <n-descriptions :column="2" size="small" bordered>
            <n-descriptions-item label="负责人">{{ detail.item.owner || '--' }}</n-descriptions-item>
            <n-descriptions-item label="角色">{{ detail.item.owner_role || '--' }}</n-descriptions-item>
            <n-descriptions-item label="效果分">
              {{ effectScoreText }}
            </n-descriptions-item>
            <n-descriptions-item label="样本数">{{ detail.item.effect?.samples ?? '--' }}</n-descriptions-item>
            <n-descriptions-item label="标识">{{ detail.item.asset_key }}</n-descriptions-item>
            <n-descriptions-item label="状态">{{ detail.item.state || '--' }}</n-descriptions-item>
          </n-descriptions>

          <n-alert v-if="myRequest" type="info" :bordered="false">
            <n-space align="center" :size="8">
              <span>我的申领：{{ portalStatusLabel(myRequest.status) }}</span>
              <span v-if="myRequest.decided_reason" class="muted">（{{ myRequest.decided_reason }}）</span>
              <span v-if="myRequest.expires_at" class="muted">到期时间 {{ formatTime(myRequest.expires_at) }}</span>
            </n-space>
          </n-alert>

          <n-alert v-if="resultHint" :type="resultHintType" :bordered="false">{{ resultHint }}</n-alert>

          <n-input
            v-if="canApply"
            v-model:value="reason"
            type="textarea"
            :autosize="{ minRows: 2, maxRows: 4 }"
            maxlength="200"
            show-count
            placeholder="说明用途，便于审批人判断（可选）"
          />

          <n-space justify="end">
            <n-button quaternary @click="emit('close')">关闭</n-button>
            <n-button
              v-if="canRevoke"
              type="warning"
              secondary
              :loading="submitting"
              @click="onRevoke"
            >
              放弃使用
            </n-button>
            <n-button v-if="canApply" type="primary" :loading="submitting" @click="onApply">
              申领使用
            </n-button>
          </n-space>
        </n-space>
      </template>
    </n-spin>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { NAlert, NButton, NDescriptions, NDescriptionsItem, NInput, NSpace, NSpin, NTag, useMessage } from 'naive-ui'
import {
  applyPortalAsset,
  fetchPortalAssetDetail,
  portalStatusLabel,
  revokeMyPortalRequest,
  type PortalAssetDetail,
  type PortalAssetType,
  type PortalRequestStatus,
} from '../../api/portal'

const props = defineProps<{ assetType: PortalAssetType; assetKey: string }>()
const emit = defineEmits<{ close: []; changed: [] }>()

const message = useMessage()
const loading = ref(false)
const submitting = ref(false)
const detail = ref<PortalAssetDetail | null>(null)
const error = ref('')
const reason = ref('')
const resultHint = ref('')
const resultHintType = ref<'success' | 'info' | 'warning'>('info')

const myRequest = computed(() => detail.value?.my_request || null)
const assetTypeLabel = computed(() => (props.assetType === 'skill' ? '技能' : '能力资产'))
const effectScoreText = computed(() => {
  const score = detail.value?.item.effect?.effect_score
  return typeof score === 'number' ? score.toFixed(2) : '--'
})

/** 已开通 / 待审 / 已拒绝 → 不可重复申领。 */
const canApply = computed(() => {
  if (!detail.value) return false
  if (detail.value.granted) return false
  const status = (myRequest.value?.status || '') as PortalRequestStatus | ''
  return !status || status === 'rejected' || status === 'revoked' || status === 'expired'
})

const canRevoke = computed(() => detail.value?.granted === true)

const formatTime = (value?: string | null) => (value ? new Date(value).toLocaleString() : '--')

async function load() {
  loading.value = true
  error.value = ''
  try {
    detail.value = await fetchPortalAssetDetail(props.assetType, props.assetKey)
  } catch (err: any) {
    const status = err?.response?.status
    error.value =
      status === 404
        ? '该资产未上架或已下线，无法申领。'
        : err?.response?.data?.detail || '加载资产详情失败，请稍后重试。'
  } finally {
    loading.value = false
  }
}

async function onApply() {
  if (!detail.value) return
  submitting.value = true
  resultHint.value = ''
  try {
    const result = await applyPortalAsset({
      assetType: props.assetType,
      assetKey: props.assetKey,
      reason: reason.value,
    })
    if (result.status === 'already_granted') {
      resultHintType.value = 'success'
      resultHint.value = '你已开通该资产，无需重复申领。'
    } else if (result.status === 'pending') {
      resultHintType.value = 'info'
      resultHint.value = '已提交过申领，正在等待审批。'
    } else {
      resultHintType.value = 'success'
      resultHint.value = '申领已提交，审批通过后自动开通。'
    }
    reason.value = ''
    await load()
    emit('changed')
  } catch (err: any) {
    const status = err?.response?.status
    if (status === 409) {
      resultHintType.value = 'warning'
      resultHint.value = '暂时无法确定审批人，请联系管理员。'
    } else if (status === 404) {
      resultHintType.value = 'warning'
      resultHint.value = '该资产已下线，申领失败。'
    } else {
      message.error(err?.response?.data?.detail || '申领失败，请稍后重试。')
    }
  } finally {
    submitting.value = false
  }
}

async function onRevoke() {
  const requestId = myRequest.value?.request_id
  if (!requestId) return
  submitting.value = true
  try {
    await revokeMyPortalRequest(requestId, '用户主动放弃')
    message.success('已放弃该资产的使用权限。')
    await load()
    emit('changed')
  } catch (err: any) {
    message.error(err?.response?.data?.detail || '操作失败，请稍后重试。')
  } finally {
    submitting.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.portal-detail {
  min-height: 120px;
}
.detail-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.detail-head h3 {
  margin: 0 0 4px;
  font-size: 16px;
}
.detail-head p {
  margin: 0;
  font-size: 13px;
}
</style>
