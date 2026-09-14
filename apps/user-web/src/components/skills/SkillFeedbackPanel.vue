<template>
  <section class="feedback">
    <header>
      <div class="heading">
        <div class="title-line">
          <strong>{{ t('skills.feedback.title') }}</strong>
          <span class="total">{{ t('skills.feedback.total', { count: commentCount }) }}</span>
          <n-tag v-if="unreadCount" type="error" size="small" round>{{ t('skills.feedback.unread', { count: unreadCount }) }}</n-tag>
        </div>
      </div>
      <n-button size="small" :type="thread.likedByMe ? 'primary' : 'default'" secondary round @click="likeSkill">{{ thread.likedByMe ? '♥' : '♡' }} {{ thread.likes }}</n-button>
    </header>
    <n-spin :show="loading">
      <div v-if="groups.length" class="comments">
        <section v-for="group in groups" :key="group.root.id">
          <FeedbackCommentItem :comment="group.root" @reply="startReply" @like="likeComment" @delete="remove" />
          <FeedbackCommentItem v-for="reply in group.replies" :key="reply.id" :comment="reply" nested @reply="startReply" @like="likeComment" @delete="remove" />
        </section>
      </div>
      <n-empty v-else-if="!loading" size="small" :description="t('skills.feedback.empty')" class="empty" />
      <div v-if="thread.hasMore" class="load-more"><n-button secondary size="small" :loading="loadingMore" @click="loadMore">{{ t('ui.load_more') }}</n-button></div>
    </n-spin>
    <div v-if="replying" class="replying">
      <span>{{ t('skills.feedback.replying_to', { name: replying.author.displayName || t('skills.feedback.member') }) }}</span>
      <n-button text size="tiny" @click="replying = null">{{ t('ui.cancel') }}</n-button>
    </div>
    <div class="composer">
      <n-input v-model:value="content" type="textarea" :autosize="{ minRows: 2, maxRows: 5 }" maxlength="2000" show-count :placeholder="replying ? t('skills.feedback.reply_placeholder') : t('skills.feedback.placeholder')" />
      <n-button type="primary" :disabled="!content.trim()" :loading="sending" @click="send">{{ replying ? t('skills.feedback.reply') : t('skills.feedback.send') }}</n-button>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { NButton, NEmpty, NInput, NSpin, NTag, useMessage } from 'naive-ui'
import { addFeedbackComment, deleteFeedbackComment, fetchFeedback, toggleFeedbackCommentLike, toggleFeedbackLike, type FeedbackComment, type FeedbackThread } from '../../api/resourceFeedback'
import { t } from '../../composables/i18n'
import FeedbackCommentItem from './FeedbackCommentItem.vue'

const props = withDefaults(defineProps<{ resourceType: string; resourceId: string; commentCount?: number; unreadCount?: number }>(), {
  commentCount: 0,
  unreadCount: 0,
})
const emit = defineEmits<{ read: []; changed: [] }>()
const message = useMessage(), loading = ref(false), loadingMore = ref(false), sending = ref(false), content = ref(''), replying = ref<FeedbackComment | null>(null)
const thread = reactive<FeedbackThread>({ items: [], likes: 0, likedByMe: false, hasMore: false, nextCursor: '' })
const groups = computed(() => {
  const byId = new Map(thread.items.map(item => [item.id, item]))
  const roots = thread.items.filter(item => !item.rootId || !byId.has(item.rootId))
  return roots.map(root => ({ root, replies: thread.items.filter(item => item.id !== root.id && item.rootId === root.id).slice().reverse() }))
})

async function load(append = false) {
  append ? loadingMore.value = true : loading.value = true
  try {
    const data = await fetchFeedback(props.resourceType, props.resourceId, append ? thread.nextCursor : '')
    thread.items = append ? [...thread.items, ...data.items] : data.items
    thread.likes = data.likes; thread.likedByMe = data.likedByMe; thread.hasMore = data.hasMore; thread.nextCursor = data.nextCursor
    emit('read')
  } catch { message.error(t('skills.feedback.load_failed')) }
  finally { loading.value = false; loadingMore.value = false }
}
async function send() {
  if (!content.value.trim()) return
  sending.value = true
  try {
    const item = await addFeedbackComment(props.resourceType, props.resourceId, content.value, replying.value?.id || '')
    thread.items.unshift(item); content.value = ''; replying.value = null; emit('changed')
  } catch { message.error(t('skills.feedback.send_failed')) }
  finally { sending.value = false }
}
function startReply(item: FeedbackComment) { replying.value = item }
async function likeSkill() { try { Object.assign(thread, await toggleFeedbackLike(props.resourceType, props.resourceId)) } catch { message.error(t('skills.feedback.like_failed')) } }
async function likeComment(item: FeedbackComment) { try { Object.assign(item, await toggleFeedbackCommentLike(item.id)) } catch { message.error(t('skills.feedback.like_failed')) } }
async function remove(item: FeedbackComment) { try { await deleteFeedbackComment(item.id); thread.items = thread.items.filter(row => row.id !== item.id); emit('changed') } catch { message.error(t('skills.feedback.delete_failed')) } }
function loadMore() { void load(true) }
watch(() => props.resourceId, () => { replying.value = null; content.value = ''; void load() })
onMounted(() => void load())
</script>

<style scoped>
.feedback{display:grid;gap:14px}.feedback>header{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:2px 0 10px;border-bottom:1px solid #edf0f5}.heading{min-width:0}.title-line{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.total{color:#667085;font-size:13px;font-weight:400}.comments{max-height:480px;overflow:auto}.empty{padding:54px 0}.load-more{text-align:center;padding:12px}.replying{display:flex;align-items:center;justify-content:space-between;padding:9px 12px;border-radius:9px;color:#52627d;background:#f2f5fa;font-size:12px}.composer{display:flex;align-items:flex-end;gap:10px}.composer :deep(.n-input){flex:1}
</style>
