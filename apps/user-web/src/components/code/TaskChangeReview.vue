<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import SearchOutline from '@vicons/ionicons5/es/SearchOutline'
import { getDshTaskFileDiff } from '../../platform'
import type { DshTaskChangeSet, DshTaskFileDiff } from '../../platform/types'
import CodeFileTypeIcon from './CodeFileTypeIcon.vue'
import UnifiedDiffView from './UnifiedDiffView.vue'
import { changeStatusPresentation } from './changePresentation'

const props = defineProps<{
  sessionId: string
  changes: DshTaskChangeSet
  requestedPath?: string
  locale?: 'zh' | 'en'
}>()
const emit = defineEmits<{ (event: 'open-diff', path: string): void }>()
const selected = ref('')
const fileDiff = ref<DshTaskFileDiff | null>(null)
const filter = ref('')
const loading = ref(false)
const error = ref('')
const visibleFiles = computed(() => props.changes.files.filter(file => file.path.toLowerCase().includes(filter.value.trim().toLowerCase())))
const selectedChange = computed(() => props.changes.files.find(file => file.path === selected.value))
const selectedName = computed(() => selected.value.split('/').pop() || selected.value)
const selectedDirectory = computed(() => selected.value.includes('/') ? selected.value.slice(0, selected.value.lastIndexOf('/')) : '')
const selectedStatus = computed(() => changeStatusPresentation(selectedChange.value?.status || '', props.locale))

async function select(path: string) {
  if (!path) return
  selected.value = path; loading.value = true; error.value = ''; fileDiff.value = null
  try { fileDiff.value = await getDshTaskFileDiff(props.sessionId, props.changes.task_id, path) }
  catch (value) { error.value = value instanceof Error ? value.message : String(value) }
  finally { loading.value = false }
}
function selectRequested() {
  const requested = props.requestedPath && props.changes.files.some(file => file.path === props.requestedPath)
    ? props.requestedPath : props.changes.files[0]?.path
  if (requested && requested !== selected.value) void select(requested)
}
watch(() => [props.changes.task_id, props.requestedPath] as const, selectRequested, { immediate: true })
</script>

<template>
  <div class="task-review">
    <nav>
      <div class="overview">
        <strong>{{ locale === 'en' ? 'This task' : '本次任务' }}</strong>
        <span>{{ changes.files.length }} {{ locale === 'en' ? 'files' : '个文件' }}</span>
        <code><b>+{{ changes.additions }}</b><i>-{{ changes.deletions }}</i></code>
      </div>
      <label class="filter"><SearchOutline /><input v-model="filter" :placeholder="locale === 'en' ? 'Filter files…' : '筛选变更文件…'" /></label>
      <div class="file-list">
        <button v-for="file in visibleFiles" :key="file.path" type="button" :class="{ selected: selected === file.path }" @click="select(file.path)" @dblclick="emit('open-diff', file.path)">
          <CodeFileTypeIcon :path="file.path" />
          <span :title="file.path">{{ file.path }}</span>
          <code v-if="file.binary">BIN</code>
          <code v-else><b>+{{ file.additions || 0 }}</b><i>-{{ file.deletions || 0 }}</i></code>
        </button>
        <div v-if="!visibleFiles.length" class="empty">{{ locale === 'en' ? 'No matching files' : '没有匹配的文件' }}</div>
      </div>
    </nav>
    <main>
      <div v-if="selected" class="diff-heading">
        <CodeFileTypeIcon :path="selected" />
        <div class="file-title"><strong>{{ selectedName }}</strong><span v-if="selectedDirectory">{{ selectedDirectory }}</span></div>
        <span class="status" :class="`tone-${selectedStatus.tone}`">{{ selectedStatus.label }}</span>
      </div>
      <div v-if="error" class="empty error">{{ error }}</div>
      <div v-else-if="loading" class="empty">{{ locale === 'en' ? 'Loading task diff…' : '正在读取本次任务的变更…' }}</div>
      <UnifiedDiffView v-else-if="fileDiff?.diff" :diff="fileDiff.diff" :path="selected" />
      <div v-else class="empty">{{ locale === 'en' ? 'Select a file to review.' : '选择文件后查看本次任务的具体变更。' }}</div>
    </main>
  </div>
</template>

<style scoped>
.task-review{display:grid;height:100%;min-height:0;grid-template-columns:minmax(270px,38%) minmax(0,1fr)}nav{display:flex;min-width:0;min-height:0;flex-direction:column;border-right: 1px solid var(--mg-border);background: var(--mg-bg-surface)}.overview{display:flex;height:52px;flex:none;align-items:center;gap:8px;border-bottom: 1px solid var(--mg-border);padding:0 12px;color: var(--mg-text-3);font-size:10px}.overview strong{color: var(--mg-text-1);font-size:12px}.overview span{flex:1}.overview code,.file-list code{display:flex;gap:5px;font:10px ui-monospace,SFMono-Regular,Menlo,monospace}.overview b,.file-list b{color: var(--mg-success-text)}.overview i,.file-list i{color: var(--mg-danger-text);font-style:normal}.filter{display:flex;height:34px;flex:none;align-items:center;gap:7px;margin:10px 10px 7px;border: 1px solid var(--mg-border);border-radius:8px;background: var(--mg-bg-surface);padding:0 9px;color: var(--mg-text-3)}.filter:focus-within{border-color: var(--mg-brand-soft-border);box-shadow:0 0 0 3px #dbeafe80}.filter svg{width:14px}.filter input{min-width:0;flex:1;border:0;outline:0;background:transparent;color: var(--mg-text-1);font-size:11px}.file-list{min-height:0;flex:1;overflow:auto;padding:0 7px 12px}.file-list button{display:flex;width:100%;height:36px;align-items:center;gap:7px;border:0;border-radius:7px;background:transparent;padding:0 7px;color: var(--mg-text-2);text-align:left;cursor:pointer}.file-list button:hover{background: #eef3f8}.file-list button.selected{background: #e8f0fd;color: var(--mg-brand)}.file-list button>span{min-width:0;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font:10px ui-monospace,SFMono-Regular,Menlo,monospace}main{min-width:0;overflow:auto;background: var(--mg-bg-surface)}.diff-heading{position:sticky;z-index:3;top:0;display:flex;height:52px;align-items:center;gap:9px;border-bottom: 1px solid var(--mg-border);background: var(--mg-bg-surface);padding:0 14px}.file-title{display:flex;min-width:0;flex:1;flex-direction:column;gap:2px}.file-title strong,.file-title span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.file-title strong{color: var(--mg-text-1);font-size:12px}.file-title span{color: var(--mg-text-3);font:9px ui-monospace,SFMono-Regular,Menlo,monospace}.status{font:700 10px ui-monospace,SFMono-Regular,Menlo,monospace;color: var(--mg-text-3)}.tone-added{color: var(--mg-success-text)}.tone-modified{color: var(--mg-warning-text)}.tone-deleted,.tone-conflict{color: var(--mg-danger-text)}.tone-renamed{color: var(--mg-accent-violet-text)}.empty{display:grid;min-height:110px;place-items:center;padding:18px;color: var(--mg-text-3);font-size:11px}.error{color: var(--mg-danger-text)}:global(html.theme-dark) nav{border-color: var(--mg-brand-soft-border);background: var(--mg-bg-app)}:global(html.theme-dark) .overview{border-color: var(--mg-brand-soft-border);color: var(--mg-text-3)}:global(html.theme-dark) .overview strong{color: var(--mg-text-1)}:global(html.theme-dark) .filter{border-color: var(--mg-brand-soft-border);background: var(--mg-bg-app)}:global(html.theme-dark) .filter input{color: var(--mg-text-1)}:global(html.theme-dark) .file-list button{color: var(--mg-text-2)}:global(html.theme-dark) .file-list button:hover{background: var(--mg-bg-app)}:global(html.theme-dark) .file-list button.selected{background: var(--mg-bg-app);color: var(--mg-brand-text)}:global(html.theme-dark) main{background: var(--mg-bg-app)}:global(html.theme-dark) .diff-heading{border-color: var(--mg-brand-soft-border);background: var(--mg-bg-app)}:global(html.theme-dark) .file-title strong{color: var(--mg-text-1)}
</style>
