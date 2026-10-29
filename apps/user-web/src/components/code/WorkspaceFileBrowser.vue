<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { listDshWorkspaceDirectory } from '../../platform'
import type { DshDirectoryEntry } from '../../platform/types'
import WorkspaceFileTreeNode from './WorkspaceFileTreeNode.vue'
import WorkspaceFilePreview from './WorkspaceFilePreview.vue'

const props = defineProps<{ sessionId: string; locale?: 'zh' | 'en'; requestedPath?: string }>()
const emit = defineEmits<{ (event: 'open-file', path: string): void }>()
const roots = ref<DshDirectoryEntry[]>([])
const selectedPath = ref('')
const error = ref('')

async function loadRoot() {
  error.value = ''
  try { roots.value = await listDshWorkspaceDirectory(props.sessionId) }
  catch (value) { error.value = String(value) }
}

async function select(entry: DshDirectoryEntry) {
  await selectPath(entry.path)
}

async function selectPath(path: string) {
  selectedPath.value = path
}

watch(() => props.sessionId, loadRoot)
watch(() => props.requestedPath, path => { if (path && path !== selectedPath.value) void selectPath(path) })
onMounted(loadRoot)
onMounted(() => { if (props.requestedPath) void selectPath(props.requestedPath) })
</script>

<template>
  <div class="file-browser">
    <nav aria-label="Workspace files">
      <WorkspaceFileTreeNode v-for="entry in roots" :key="entry.path" :session-id="sessionId" :entry="entry" :selected-path="selectedPath" @select="select" @open="emit('open-file', $event)" />
    </nav>
    <main><div v-if="error" class="state error">{{ error }}</div><WorkspaceFilePreview v-else :session-id="sessionId" :path="selectedPath" :locale="locale" /></main>
  </div>
</template>

<style scoped>
.file-browser{display:grid;min-height:0;height:100%;grid-template-columns:230px minmax(0,1fr)}nav{overflow:auto;border-right: 1px solid var(--mg-border);padding:8px 6px}main{min-width:0;overflow:auto;background: var(--mg-bg-surface)}.preview-heading{position:sticky;z-index:2;top:0;display:flex;min-height:48px;align-items:center;justify-content:space-between;gap:12px;border-bottom: 1px solid var(--mg-border);background: var(--mg-bg-surface);padding:0 14px;color: var(--mg-text-1)}.preview-file{display:flex;min-width:0;align-items:center;gap:7px}.preview-file strong{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12px}.preview-heading>span{flex:none;color: var(--mg-text-3);font:10px ui-monospace,SFMono-Regular,Menlo,monospace}.state{display:grid;height:100%;place-items:center;padding:24px;color: var(--mg-text-3);font-size:12px}.state.error{color: var(--mg-danger-text)}.image-preview{display:block;max-width:100%;max-height:calc(100% - 48px);margin:auto;padding:18px;object-fit:contain}.truncated{position:sticky;bottom:0;background: var(--mg-warning-bg);padding:7px 12px;color: var(--mg-warning-text);font-size:11px}:global(html.theme-dark) main{background: var(--mg-bg-app)}:global(html.theme-dark) .preview-heading{border-color: var(--mg-brand-soft-border);background: var(--mg-bg-app);color: var(--mg-text-1)}:global(html.theme-dark) .preview-heading>span{color: var(--mg-text-3)}:global(html.theme-dark) .state.error{color: var(--mg-danger-text)}:global(html.theme-dark) .truncated{background: var(--mg-warning-bg);color: #ffedd5}
</style>
