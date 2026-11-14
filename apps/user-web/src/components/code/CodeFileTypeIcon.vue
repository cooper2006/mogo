<script setup lang="ts">
import { computed } from 'vue'
import CodeOutline from '@vicons/ionicons5/es/CodeOutline'
import DocumentOutline from '@vicons/ionicons5/es/DocumentOutline'
import LogoCss3 from '@vicons/ionicons5/es/LogoCss3'
import LogoHtml5 from '@vicons/ionicons5/es/LogoHtml5'
import LogoJavascript from '@vicons/ionicons5/es/LogoJavascript'
import LogoMarkdown from '@vicons/ionicons5/es/LogoMarkdown'
import LogoNodejs from '@vicons/ionicons5/es/LogoNodejs'
import LogoPython from '@vicons/ionicons5/es/LogoPython'
import LogoVue from '@vicons/ionicons5/es/LogoVue'
import { fileTypePresentation } from './changePresentation'

const props = defineProps<{ path: string }>()
const type = computed(() => fileTypePresentation(props.path))
const icon = computed(() => {
  const map = {
    javascript: LogoJavascript,
    python: LogoPython,
    vue: LogoVue,
    web: LogoHtml5,
    style: LogoCss3,
    markdown: LogoMarkdown,
    shell: LogoNodejs,
    native: CodeOutline,
  } as const
  const tone = type.value.tone
  return tone in map ? map[tone as keyof typeof map] : undefined
})
</script>

<template>
  <span class="file-type" :class="`tone-${type.tone}`" :title="type.name" :aria-label="type.name"><component :is="icon" v-if="icon" /><DocumentOutline v-else-if="type.tone === 'generic'" /><template v-else>{{ type.label }}</template></span>
</template>

<style scoped>
.file-type{display:grid;width:20px;height:20px;flex:none;place-items:center;border-radius: 4px;font:800 8px/1 ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:-.07em}.file-type svg{width:15px;height:15px}.tone-typescript{background: var(--mg-info-bg);color:var(--mg-brand-text)}.tone-javascript{background: var(--mg-warning-bg);color:var(--mg-warning-text)}.tone-python{background: var(--mg-info-bg);color:var(--mg-brand-text)}.tone-vue{background: var(--mg-success-bg);color:var(--mg-success-text)}.tone-json{background: var(--mg-bg-subtle);color:var(--mg-text-2)}.tone-web{background: var(--mg-warning-bg);color:var(--mg-warning-text)}.tone-style{background: var(--mg-accent-violet-bg);color:var(--mg-accent-violet-text)}.tone-markdown{background: var(--mg-neutral-bg);color:var(--mg-text-2)}.tone-config{background: var(--mg-bg-subtle);color:var(--mg-text-2)}.tone-shell{background: var(--mg-success-bg);color:var(--mg-success-text)}.tone-database{background: var(--mg-accent-teal-bg);color:var(--mg-accent-teal-text)}.tone-native{background: var(--mg-warning-bg);color:var(--mg-warning-text)}.tone-generic{color:var(--mg-text-3)}
</style>
