<script setup lang="ts">
import { computed } from 'vue'
import { highlightCode } from './codeSyntax'

const props = defineProps<{ content: string; path: string; language?: string }>()
const highlighted = computed(() => highlightCode(props.content, props.path, props.language))
</script>

<template>
  <pre class="code-preview"><code v-html="highlighted"></code></pre>
</template>

<style scoped>
.code-preview{box-sizing:border-box;min-height:100%;margin:0;padding:15px 16px;background: var(--mg-bg-surface);color: var(--mg-text-1);font:12px/1.7 ui-monospace,SFMono-Regular,Menlo,monospace;tab-size:2;white-space:pre;overflow:auto}.code-preview :deep(.hljs-comment),.code-preview :deep(.hljs-quote){color: var(--mg-text-3)}.code-preview :deep(.hljs-keyword),.code-preview :deep(.hljs-selector-tag),.code-preview :deep(.hljs-literal){color: var(--mg-accent-violet-text)}.code-preview :deep(.hljs-string),.code-preview :deep(.hljs-attr){color: var(--mg-success-text)}.code-preview :deep(.hljs-number),.code-preview :deep(.hljs-attribute){color: var(--mg-warning-text)}.code-preview :deep(.hljs-title),.code-preview :deep(.hljs-function){color: var(--mg-brand)}.code-preview :deep(.hljs-built_in),.code-preview :deep(.hljs-type){color: var(--mg-warning-text)}.code-preview :deep(.hljs-meta),.code-preview :deep(.hljs-tag){color: #0891b2}:global(html.theme-dark) .code-preview{background: var(--mg-bg-app);color: var(--mg-text-1)}:global(html.theme-dark) .code-preview :deep(.hljs-comment),:global(html.theme-dark) .code-preview :deep(.hljs-quote){color: var(--mg-text-3)}:global(html.theme-dark) .code-preview :deep(.hljs-keyword),:global(html.theme-dark) .code-preview :deep(.hljs-selector-tag),:global(html.theme-dark) .code-preview :deep(.hljs-literal){color: #c792ea}:global(html.theme-dark) .code-preview :deep(.hljs-string),:global(html.theme-dark) .code-preview :deep(.hljs-attr){color: #c3e88d}:global(html.theme-dark) .code-preview :deep(.hljs-number),:global(html.theme-dark) .code-preview :deep(.hljs-attribute){color: #f78c6c}:global(html.theme-dark) .code-preview :deep(.hljs-title),:global(html.theme-dark) .code-preview :deep(.hljs-function){color: #82aaff}:global(html.theme-dark) .code-preview :deep(.hljs-built_in),:global(html.theme-dark) .code-preview :deep(.hljs-type){color: #ffcb6b}:global(html.theme-dark) .code-preview :deep(.hljs-meta),:global(html.theme-dark) .code-preview :deep(.hljs-tag){color: #89ddff}
</style>
