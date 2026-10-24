<script setup lang="ts">
// Compact locator editor for one browser step (Line A — manual).
// The user fills in any subset of ARIA role / accessible name /
// icon class / row anchor; runtime does AND-matching. Fields are
// deliberately few so the UI stays usable without a training wheel.
//
// If a user pastes an HTML snippet into the "从 HTML 提取" box, we
// do a lightweight extraction to prefill the form — this is the
// "one-shot tool" discussed earlier, kept inline to avoid a separate
// heavyweight modal.

import { computed, ref, watch } from 'vue'
import { NButton, NCollapse, NCollapseItem, NInput, NInputGroup, NInputNumber, NSelect, NSpace } from 'naive-ui'
import type { Locator } from '../api/compositeSkill'
import { t } from '../composables/i18n'

const props = defineProps<{
  modelValue: Locator | undefined
  // For per-op steps we label the section with its op name (e.g. "editing").
  title?: string
}>()
const emit = defineEmits(['update:modelValue'])

const local = ref<Locator>({ ...(props.modelValue || {}) })
const htmlSnippet = ref<string>('')

watch(() => props.modelValue, (v) => { local.value = { ...(v || {}) } }, { deep: true })
watch(local, (v) => {
  const cleaned: Locator = {}
  for (const [k, val] of Object.entries(v)) {
    if (val === undefined || val === '' || val === null) continue
    ;(cleaned as any)[k] = val
  }
  emit('update:modelValue', Object.keys(cleaned).length ? cleaned : undefined)
}, { deep: true })

const roleOptions = [
  { label: '(any)', value: '' },
  { label: 'button', value: 'button' },
  { label: 'link', value: 'link' },
  { label: 'textbox', value: 'textbox' },
  { label: 'combobox', value: 'combobox' },
  { label: 'menuitem', value: 'menuitem' },
  { label: 'checkbox', value: 'checkbox' },
]

// 识别 iconfont 风格类名（icon-/ic-/anticon-/el-icon- 前缀）的 token。
const ICON_TOKEN_RE = /^(icon|ic|anticon|el-icon)[-_]/i

/** 从类名字符串中找出第一个图标类名 token。 */
function findIconToken(cls: string): string | undefined {
  return cls.split(/\s+/).find(t => ICON_TOKEN_RE.test(t))
}

/** 推断控件 role：显式 role 优先，其次按标签名映射，最后回退到已填值。 */
function inferRole(tag: string, explicit: string, fallback: string): string {
  return explicit
    || (tag === 'a' ? 'link'
      : tag === 'button' ? 'button'
      : tag === 'input' ? 'textbox'
      : tag === 'textarea' ? 'textbox'
      : tag === 'select' ? 'combobox'
      : fallback)
}

/** 提取图标类名：先看自身，再看单个子元素上的图标类（如 <i class="iconfont xxx">）。 */
function extractIconClass(el: HTMLElement): string | undefined {
  const iconTok = findIconToken((el.className || '').toString())
  if (iconTok) return iconTok
  const child = el.querySelector('[class*="icon"]')
  if (child) return findIconToken((child.className || '').toString())
  return undefined
}

// Tiny, local HTML → locator signal extractor. Uses DOMParser; no deps.
function extractFromHTML() {
  const src = htmlSnippet.value.trim()
  if (!src) return
  try {
    const doc = new DOMParser().parseFromString(src, 'text/html')
    const el = doc.body.firstElementChild as HTMLElement | null
    if (!el) return
    const next: Locator = { ...local.value }
    next.role = inferRole(el.tagName.toLowerCase(), el.getAttribute('role')?.toLowerCase() || '', next.role || '')
    const aria = el.getAttribute('aria-label') || ''
    if (aria) next.aria_label = aria
    const txt = (el.textContent || '').replace(/\s+/g, ' ').trim()
    if (txt) next.text = txt.slice(0, 120)
    // iconfont-style class detection
    const iconClass = extractIconClass(el)
    if (iconClass) next.icon_class = iconClass
    local.value = next
  } catch { /* bad HTML snippet */ }
}

const hasAny = computed(() => Object.values(local.value).some(v => v !== undefined && v !== ''))

function clearAll() { local.value = {} }
</script>

<template>
  <n-collapse>
    <n-collapse-item :title="title || t('locator.title')" :name="'loc'">
      <div class="space-y-2">
        <n-input-group>
          <n-select
            v-model:value="local.role"
            :options="roleOptions"
            size="small"
            style="width: 130px"
            placeholder="role"
          />
          <n-input v-model:value="local.name" size="small" :placeholder="t('locator.exact_match')" />
        </n-input-group>

        <n-input-group>
          <n-input v-model:value="local.name_contains" size="small" :placeholder="t('locator.substring_match')" />
          <n-input v-model:value="local.icon_class" size="small" :placeholder="t('locator.icon_class')" />
        </n-input-group>

        <n-input-group>
          <n-input v-model:value="local.aria_label" size="small" placeholder="aria-label" />
          <n-input v-model:value="local.text" size="small" placeholder="visible text" />
        </n-input-group>

        <n-input-group>
          <n-input
            v-model:value="local.ancestor_contains_text"
            size="small"
            :placeholder="t('locator.ancestor_text')"
          />
          <n-input-number
            v-model:value="local.nth"
            size="small"
            :min="0"
            placeholder="nth"
            style="width: 100px"
          />
        </n-input-group>

        <div class="border-t border-dashed border-gray-200 pt-2 mt-2">
          <div class="text-xs text-gray-500 mb-1">{{ t('locator.auto_fill_desc') }}</div>
          <n-input
            v-model:value="htmlSnippet"
            type="textarea"
            :autosize="{ minRows: 2, maxRows: 4 }"
            :placeholder="t('locator.auto_fill_placeholder')"
          />
          <n-space :size="6" class="mt-1">
            <n-button size="tiny" @click="extractFromHTML">{{ t('locator.btn_extract') }}</n-button>
            <n-button size="tiny" quaternary :disabled="!hasAny" @click="clearAll">{{ t('locator.btn_clear') }}</n-button>
          </n-space>
        </div>
      </div>
    </n-collapse-item>
  </n-collapse>
</template>
