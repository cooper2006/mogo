<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { NDrawer, NDrawerContent, NButton, NEmpty, NTag, NInput, NSpace, NModal } from 'naive-ui'
import {
  commitSession,
  listSessionVersions,
  shareSession,
  upsertCoPresence,
  getCoPresence,
  type SessionVersion,
  type ShareView,
  type PresenceView,
} from '../api/sessionVersioning'
import { t } from '../composables/i18n'

const props = defineProps<{
  open: boolean
  sessionId?: string
  authToken?: string | null
  userId?: string
  latestSeq?: number
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'commit-created', version: SessionVersion): void
  (e: 'share-created', share: ShareView): void
  (e: 'presence-changed', presence: PresenceView): void
}>()

const versions = ref<SessionVersion[]>([])
const versionsLoading = ref(false)
const shareBusy = ref(false)
const shareView = ref<ShareView | null>(null)
const shareModal = ref(false)
const shareTarget = ref('')
const online = ref<string[]>([])
let pollTimer: number | undefined

async function loadVersions() {
  if (!props.sessionId) return
  versionsLoading.value = true
  try {
    versions.value = await listSessionVersions(props.sessionId, props.authToken)
    // 真实最新 seq 取最近一次版本快照的 seq；无版本时回退到 props.latestSeq（近似）。
    resolvedLatestSeq.value =
      versions.value.length > 0
        ? Math.max(versions.value[versions.value.length - 1].seq ?? 0, props.latestSeq ?? 0)
        : props.latestSeq ?? 0
  } catch {
    versions.value = []
    resolvedLatestSeq.value = props.latestSeq ?? 0
  } finally {
    versionsLoading.value = false
  }
}

const resolvedLatestSeq = ref(0)

async function commitNow() {
  if (!props.sessionId) return
  const version = await commitSession(
    props.sessionId,
    {
      seq: resolvedLatestSeq.value || props.latestSeq || 0,
      trigger: 'manual',
      summary: '',
    },
    props.authToken,
  )
  emit('commit-created', version)
  await loadVersions()
}

async function shareNow() {
  if (!props.sessionId || !shareTarget.value.trim()) return
  shareBusy.value = true
  try {
    const view = await shareSession(
      props.sessionId,
      { receiver: shareTarget.value.trim(), visibility: 'user', receiver_role: 'viewer', ttl_seconds: 300 },
      props.authToken,
    )
    shareView.value = view
    shareModal.value = true
    emit('share-created', view)
  } finally {
    shareBusy.value = false
  }
}

async function refreshPresence() {
  if (!props.sessionId) return
  try {
    const view = await getCoPresence(props.sessionId, props.authToken)
    online.value = view.onlineUsers ?? []
    emit('presence-changed', view)
  } catch {
    online.value = []
  }
}

async function beat() {
  if (!props.sessionId) return
  try {
    await upsertCoPresence(props.sessionId, { userId: props.userId ?? '', messageSeqs: [] }, props.authToken)
  } catch {
    /* best-effort presence beat */
  }
}

watch(
  () => props.open,
  (open) => {
    if (open) {
      loadVersions()
      refreshPresence()
      beat()
    }
  },
)

onMounted(() => {
  if (props.open) {
    loadVersions()
    refreshPresence()
  }
})

watch(
  () => props.open,
  (open) => {
    if (open) {
      pollTimer = window.setInterval(() => {
        if (props.open) {
          refreshPresence()
          beat()
        }
      }, 5000)
    } else {
      if (pollTimer) {
        window.clearInterval(pollTimer)
        pollTimer = undefined
      }
    }
  },
)

onBeforeUnmount(() => {
  if (pollTimer) {
    window.clearInterval(pollTimer)
    pollTimer = undefined
  }
})

const latestSnapshotId = computed(() => {
  if (!versions.value.length) return undefined
  return versions.value[versions.value.length - 1]?.snapshotId
})
</script>

<template>
  <NDrawer :show="open" :width="360" @close="emit('close')">
    <NDrawerContent :title="t('会话版本与协作')">
      <NSpace vertical :size="14">
        <section>
          <h4 style="margin: 0 0 8px">{{ t('版本历史') }}</h4>
          <NEmpty v-if="!versionsLoading && versions.length === 0" :description="t('暂无版本快照')" style="padding: 12px 0" />
          <div v-else style="max-height: 200px; overflow-y: auto">
            <div v-for="v in versions" :key="v.snapshotId" style="padding: 6px 0; border-bottom: 1px solid #f0f0f0">
              <div style="display: flex; gap: 8px; align-items: center">
                <NTag size="small" type="info">{{ v.trigger }}</NTag>
                <span style="font-size: 12px; color: #666">seq={{ v.seq }}</span>
              </div>
              <div style="font-size: 13px; margin-top: 4px; color: #333">{{ v.summary || '—' }}</div>
              <div v-if="v.createdAt" style="font-size: 11px; color: #999; margin-top: 2px">
                {{ new Date(v.createdAt).toLocaleString() }}
              </div>
            </div>
          </div>
          <NSpace style="margin-top: 10px">
            <NButton size="small" type="primary" @click="commitNow">{{ t('提交版本') }}</NButton>
            <NButton size="small" :disabled="!latestSnapshotId" @click="emit('close')">{{ t('关闭') }}</NButton>
          </NSpace>
        </section>

        <section>
          <h4 style="margin: 0 0 8px">{{ t('分享会话') }}</h4>
          <NSpace align="center">
            <NInput v-model:value="shareTarget" :placeholder="t('收件人 userId')" style="width: 160px" />
            <NButton size="small" type="primary" :loading="shareBusy" @click="shareNow">{{ t('生成分享') }}</NButton>
          </NSpace>
        </section>

        <section>
          <h4 style="margin: 0 0 8px">{{ t('在线成员') }}</h4>
          <div v-if="online.length === 0" style="color: #999; font-size: 13px">{{ t('暂无在线成员') }}</div>
          <div v-else style="display: flex; flex-wrap: wrap; gap: 6px">
            <NTag v-for="uid in online" :key="uid" size="small" type="success">{{ uid }}</NTag>
          </div>
        </section>
      </NSpace>
    </NDrawerContent>
  </NDrawer>

  <NModal :show="shareModal" @close="shareModal = false">
    <div style="padding: 16px">
      <h4 style="margin: 0 0 8px">{{ t('分享链接') }}</h4>
      <NInput :value="shareView?.share_id ?? ''" readonly style="width: 100%; margin-bottom: 8px" />
      <div style="font-size: 12px; color: #999">
        {{ t('该链接将在 5 分钟内有效，仅可一次性兑换。') }}
      </div>
      <NSpace style="margin-top: 12px" justify="end">
        <NButton @click="shareModal = false">{{ t('关闭') }}</NButton>
      </NSpace>
    </div>
  </NModal>
</template>
