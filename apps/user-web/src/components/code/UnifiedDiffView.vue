<script setup lang="ts">
import { computed } from 'vue'
import { highlightCode } from './codeSyntax'
import { parseUnifiedDiff } from './unifiedDiff'

const props = defineProps<{ diff: string; path: string }>()
const lines = computed(() => parseUnifiedDiff(props.diff))
const lineNumber = (line: { oldLine: number | null; newLine: number | null }) => line.newLine ?? line.oldLine ?? ''
const highlightedLine = (line: { content: string; kind: string }) => {
  if (!['add', 'delete', 'context'].includes(line.kind)) return line.content.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  const marker = line.content[0] || ''
  return `<span class="diff-marker">${marker}</span>${highlightCode(line.content.slice(1), props.path)}`
}
</script>

<template>
  <div class="diff-table" role="table" aria-label="Code diff">
    <div v-for="line in lines" :key="line.id" class="diff-row" :class="line.kind" role="row">
      <span class="line-number" role="cell">{{ lineNumber(line) }}</span>
      <code role="cell" v-html="highlightedLine(line) || ' '"></code>
    </div>
  </div>
</template>

<style scoped>
.diff-table{width:max-content;min-width:100%;padding:10px 0 18px;color: var(--mg-text-1);font:11px/1.65 ui-monospace,SFMono-Regular,Menlo,monospace}.diff-row{display:grid;min-height:18px;grid-template-columns:44px minmax(max-content,1fr)}.line-number{position:sticky;z-index:1;left:0;display:block;box-sizing:border-box;background: var(--mg-bg-surface);padding:0 9px 0 4px;border-right: 1px solid var(--mg-border);color: var(--mg-text-3);text-align:right;user-select:none}.diff-row code{display:block;padding:0 14px;white-space:pre}.diff-row.add{background: var(--mg-success-bg);color: var(--mg-success-text)}.diff-row.delete{background: var(--mg-danger-bg);color: var(--mg-danger-text)}.diff-row.hunk{margin:5px 0;background: var(--mg-info-bg);color: var(--mg-brand)}.diff-row.hunk .line-number{background: var(--mg-info-bg)}.diff-row.add .line-number{background: var(--mg-success-bg);color: var(--mg-success-text)}.diff-row.delete .line-number{background: var(--mg-danger-bg);color: var(--mg-danger-text)}.diff-row :deep(.diff-marker){display:inline-block;width:10px;color:inherit}.diff-row :deep(.hljs-comment),.diff-row :deep(.hljs-quote){color: var(--mg-text-3)}.diff-row :deep(.hljs-keyword),.diff-row :deep(.hljs-literal){color: var(--mg-accent-violet-text)}.diff-row :deep(.hljs-string),.diff-row :deep(.hljs-attr){color: var(--mg-success-text)}.diff-row :deep(.hljs-number),.diff-row :deep(.hljs-attribute){color: var(--mg-warning-text)}.diff-row.meta{color: var(--mg-text-3)}:global(html.theme-dark) .diff-table{color: var(--mg-text-1)}:global(html.theme-dark) .line-number{background: var(--mg-bg-app);border-color: var(--mg-border);color: var(--mg-text-3)}:global(html.theme-dark) .diff-row.add{background: var(--mg-bg-app);color: var(--mg-success-text)}:global(html.theme-dark) .diff-row.delete{background: var(--mg-danger-bg);color: var(--mg-danger-text)}:global(html.theme-dark) .diff-row.hunk{background: var(--mg-bg-app);color: var(--mg-brand-text)}:global(html.theme-dark) .diff-row.hunk .line-number{background: var(--mg-bg-app)}:global(html.theme-dark) .diff-row.add .line-number{background: var(--mg-bg-app);color: var(--mg-success-text)}:global(html.theme-dark) .diff-row.delete .line-number{background: var(--mg-bg-app);color: var(--mg-danger-text)}:global(html.theme-dark) .diff-row :deep(.hljs-comment),:global(html.theme-dark) .diff-row :deep(.hljs-quote){color: var(--mg-text-3)}:global(html.theme-dark) .diff-row :deep(.hljs-keyword),:global(html.theme-dark) .diff-row :deep(.hljs-literal){color: var(--mg-accent-violet-text)}:global(html.theme-dark) .diff-row :deep(.hljs-string),:global(html.theme-dark) .diff-row :deep(.hljs-attr){color: var(--mg-success-text)}:global(html.theme-dark) .diff-row :deep(.hljs-number),:global(html.theme-dark) .diff-row :deep(.hljs-attribute){color: var(--mg-warning-text)}:global(html.theme-dark) .diff-row.meta{color: var(--mg-text-3)}
</style>
