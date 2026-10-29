<script setup lang="ts">
import GlobeOutline from '@vicons/ionicons5/es/GlobeOutline'
import {
  activateEmbeddedBrowserSession,
  capabilities,
  selectEmbeddedBrowserSession,
} from '../../platform'
import { useLocale } from '../../composables/i18n'

const { locale } = useLocale()
const props = defineProps<{ sessionId?: string; iconOnly?: boolean; active?: boolean }>()
const emit = defineEmits<{ (event: 'open'): void }>()

async function openBrowser() {
  if (!props.sessionId) return
  await selectEmbeddedBrowserSession(props.sessionId)
  await activateEmbeddedBrowserSession(props.sessionId)
  emit('open')
}
</script>

<template>
  <button
    v-if="capabilities.embeddedBrowser"
    :disabled="!sessionId"
    type="button"
    class="browser-test-button"
    :class="{ 'icon-only': iconOnly, active }"
    :aria-label="locale === 'zh' ? '打开测试浏览器' : 'Open test browser'"
    :title="locale === 'zh' ? '打开浏览器进行人工测试' : 'Open browser for manual testing'"
    @click="openBrowser"
  >
    <GlobeOutline />
    <span v-if="!iconOnly">{{ locale === 'zh' ? '测试浏览器' : 'Test browser' }}</span>
  </button>
</template>

<style scoped>
.browser-test-button { display: inline-flex; height: 36px; flex: none; align-items: center; justify-content: center; gap: 6px; border: 1px solid var(--mg-border); border-radius: 18px; background: rgba(255, 255, 255, .95); padding: 0 12px; color: var(--mg-text-2); font-size: 13px; font-weight: 500; letter-spacing: 0; cursor: pointer; box-shadow: 0 1px 2px rgba(15, 23, 42, .05); transition: border-color 150ms ease, background-color 150ms ease, color 150ms ease; }
.browser-test-button:hover { border-color: var(--mg-info-border); background: var(--mg-info-bg); color: var(--mg-brand); }
.browser-test-button:focus-visible { outline: 2px solid #bfdbfe; outline-offset: 2px; }
.browser-test-button:disabled { cursor: default; opacity: .45; }
.browser-test-button svg { width: 17px; height: 17px; }
.browser-test-button.icon-only { width:36px; height:36px; border: 0; border-radius: 9px; background: transparent; padding:0; box-shadow:none; }
.browser-test-button.icon-only:hover { background: var(--mg-bg-subtle); }
.browser-test-button.icon-only.active { background: var(--mg-brand-soft); color: var(--mg-brand); }
@media (max-width: 620px) { .browser-test-button { width: 36px; padding: 0; } .browser-test-button span { display: none; } }
</style>
