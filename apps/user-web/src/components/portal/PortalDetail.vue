<template>
  <div class="portal-detail">
    <n-spin :show="loading">
      <n-alert v-if="error" type="error" :bordered="false">{{ error }}</n-alert>

      <template v-else-if="detail">
        <n-space vertical :size="12">
          <div class="detail-head">
            <div>
              <h3>{{ detail.item.name }}</h3>
              <p class="mg-text-3 detail-desc">{{ detail.item.description || t('portal.no_description') }}</p>
            </div>
            <n-tag :type="detail.granted ? 'success' : 'default'" :bordered="false">
              {{ detail.granted ? t('portal.granted') : t('portal.not_granted') }}
            </n-tag>
          </div>

          <n-space :size="8" wrap>
            <n-tag size="small" :bordered="false">{{ assetTypeLabel }}</n-tag>
            <n-tag size="small" :bordered="false">{{ detail.item.category === 'uncategorized' ? t('portal.category.uncategorized') : detail.item.category }}</n-tag>
            <n-tag v-if="detail.item.rating" size="small" type="info" :bordered="false">
              {{ t('portal.rating', { level: detail.item.rating.level }) }}
            </n-tag>
            <n-tag v-if="detail.item.is_low_quality" size="small" type="warning" :bordered="false">{{ t('portal.low_quality') }}</n-tag>
            <n-tag v-for="tag in detail.item.tags" :key="tag" size="small" :bordered="false">{{ tag }}</n-tag>
          </n-space>

          <n-descriptions :column="2" size="small" bordered>
            <n-descriptions-item :label="t('portal.d.desc_owner')">{{ detail.item.owner || t('portal.d.missing') }}</n-descriptions-item>
            <n-descriptions-item :label="t('portal.d.desc_role')">{{ detail.item.owner_role || t('portal.d.missing') }}</n-descriptions-item>
            <n-descriptions-item :label="t('portal.d.effect_score')">
              {{ effectScoreText || t('portal.d.missing') }}
            </n-descriptions-item>
            <n-descriptions-item :label="t('portal.d.samples')">{{ detail.item.effect?.samples ?? t('portal.d.missing') }}</n-descriptions-item>
            <n-descriptions-item :label="t('portal.d.asset_key')">{{ detail.item.asset_key }}</n-descriptions-item>
            <n-descriptions-item :label="t('portal.d.state')">{{ detail.item.state || t('portal.d.missing') }}</n-descriptions-item>
          </n-descriptions>

          <n-alert type="default" :bordered="false" class="manage-status">
            <div class="mg-text-3 mg-caption">{{ t('portal.d.manage_status') }}</div>
            <div class="mg-text-2 mg-caption manage-line">
              <n-tag v-if="detail.item.rating" size="small" type="info" :bordered="false">
                {{ t('portal.rating', { level: detail.item.rating.level }) }}
              </n-tag>
              {{ t('portal.d.listed') }}：{{ detail.item.published_at ? t('portal.d.listed_yes') : t('portal.d.listed_no') }} ·
              {{ t('portal.d.desc_owner') }}：{{ detail.item.owner || t('portal.d.missing') }}
            </div>
            <a class="mg-text-2 manage-anchor" :href="adminAssetUrl" target="_blank" rel="noopener noreferrer">
              {{ t('portal.d.manage_anchor') }}
            </a>
          </n-alert>

          <n-alert v-if="myRequest" type="info" :bordered="false">
            <n-space align="center" :size="8">
              <span>{{ t('portal.my_request', { status: t(`portal.status.${myRequest.status}`) }) }}</span>
              <span v-if="myRequest.decided_reason" class="mg-text-3">（{{ myRequest.decided_reason }}）</span>
              <span v-if="myRequest.expires_at" class="mg-text-3">{{ t('portal.expires', { time: formatTime(myRequest.expires_at) }) }}</span>
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
            :placeholder="t('portal.apply_reason_placeholder')"
          />

          <n-space justify="end">
            <n-button quaternary @click="emit('close')">{{ t('portal.close') }}</n-button>
            <n-button
              v-if="canRevoke"
              type="warning"
              secondary
              :loading="submitting"
              @click="onRevoke"
            >
              {{ t('portal.revoke') }}
            </n-button>
            <n-button v-if="canApply" type="primary" :loading="submitting" @click="onApply">
              {{ t('portal.apply') }}
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
import { useI18n } from '@/composables/i18n'
import { formatAppDateTime } from '@/composables/appTimezone'
import { buildAdminSsoUrl } from '@/utils/adminUrl'
import {
  applyPortalAsset,
  fetchPortalAssetDetail,
  revokeMyPortalRequest,
  type PortalAssetDetail,
  type PortalAssetType,
  type PortalRequestStatus,
} from '../../api/portal'

const props = defineProps<{ assetType: PortalAssetType; assetKey: string }>()
const emit = defineEmits<{ close: []; changed: [] }>()

const { t } = useI18n()
const message = useMessage()
const loading = ref(false)
const submitting = ref(false)
const detail = ref<PortalAssetDetail | null>(null)
const error = ref('')
const reason = ref('')
const resultHint = ref('')
const resultHintType = ref<'success' | 'info' | 'warning'>('info')

const myRequest = computed(() => detail.value?.my_request || null)
const assetTypeLabel = computed(() =>
  props.assetType === 'skill' ? t('portal.type.skill') : t('portal.type.capability'),
)
const effectScoreText = computed(() => {
  const score = detail.value?.item.effect?.effect_score
  return typeof score === 'number' ? score.toFixed(2) : t('portal.d.missing')
})

/** 045 FR-13：只读"管理状态"锚点，跳 admin 资产中心对应资产卡片（`/assets?asset=<type>:<key>`）。 */
const adminAssetUrl = computed(() => {
  const base = buildAdminSsoUrl().replace(/\/+$/, '')
  return `${base}/assets?asset=${encodeURIComponent(`${props.assetType}:${props.assetKey}`)}`
})

/** 已开通 / 待审 / 已拒绝 → 不可重复申领。 */
const canApply = computed(() => {
  if (!detail.value) return false
  if (detail.value.granted) return false
  const status = (myRequest.value?.status || '') as PortalRequestStatus | ''
  return !status || status === 'rejected' || status === 'revoked' || status === 'expired'
})

const canRevoke = computed(() => detail.value?.granted === true)

const formatTime = (value?: string | null) => (value ? formatAppDateTime(value) : t('portal.d.missing'))

async function load() {
  loading.value = true
  error.value = ''
  try {
    detail.value = await fetchPortalAssetDetail(props.assetType, props.assetKey)
  } catch (err: any) {
    const status = err?.response?.status
    error.value =
      status === 404
        ? t('portal.not_published')
        : err?.response?.data?.detail || t('portal.load_detail_failed')
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
      resultHint.value = t('portal.hint.already_granted')
    } else if (result.status === 'pending') {
      resultHintType.value = 'info'
      resultHint.value = t('portal.hint.pending')
    } else {
      resultHintType.value = 'success'
      resultHint.value = t('portal.hint.submitted')
    }
    reason.value = ''
    await load()
    emit('changed')
  } catch (err: any) {
    const status = err?.response?.status
    if (status === 409) {
      resultHintType.value = 'warning'
      resultHint.value = t('portal.hint.no_approver')
    } else if (status === 404) {
      resultHintType.value = 'warning'
      resultHint.value = t('portal.hint.offline')
    } else {
      message.error(err?.response?.data?.detail || t('portal.apply_failed'))
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
    await revokeMyPortalRequest(requestId, t('portal.request.revoke_reason'))
    message.success(t('portal.revoke_done'))
    await load()
    emit('changed')
  } catch (err: any) {
    message.error(err?.response?.data?.detail || t('portal.operation_failed'))
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
  gap: var(--mg-space-3);
}

.detail-head h3 {
  margin: 0 0 var(--mg-space-1);
  font-size: var(--mg-font-size-lg);
  font-weight: var(--mg-weight-semibold);
  color: var(--mg-text-1);
}

.detail-head p,
.detail-desc {
  margin: 0;
  font-size: var(--mg-font-size-sm);
  line-height: var(--mg-line-relaxed);
}

.manage-status {
  padding: var(--mg-space-2) var(--mg-space-3);
}

.manage-line {
  margin: var(--mg-space-1) 0;
}

.manage-anchor {
  color: var(--mg-primary);
  text-decoration: none;
}

.manage-anchor:hover {
  text-decoration: underline;
}
</style>
