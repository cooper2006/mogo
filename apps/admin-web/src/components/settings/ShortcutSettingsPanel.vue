<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { NAlert, NInput, useMessage } from 'naive-ui'
import { t } from '@/composables/i18n'
import { fetchShortcutPlan, saveShortcutPlan, type ShortcutEntry, type ShortcutEntryType, type ShortcutGroup, type ShortcutPlan } from '@/api/shortcut-settings'
import { fetchSkills, type SkillItem } from '@/api/skills'
import { ShortcutGroupToggleIcon } from '@/icons/ShortcutGroupToggleIcon'
import { ShortcutActionIcon } from '@/icons/ShortcutActionIcon'
import { shortcutIconCatalog } from './shortcutIconCatalog'

const message = useMessage()
const loading = ref(false)
const saving = ref(false)
const plan = ref<ShortcutPlan | null>(null)
const editorVisible = ref(false)
const draft = ref({ type: 'prompt' as ShortcutEntryType, label: '', prompt: '', groupKey: '', resourceId: '' })
const skillOptions = ref<SkillItem[]>([])
const skillLoading = ref(false)
const editingEntryId = ref<string | null>(null)
const collapsedGroups = ref<Set<string>>(new Set())
const groupDraftLabels = ref<Record<string, string>>({})
const iconPickerVisible = ref(false)
const iconPickerTarget = ref<{ kind: 'group' | 'entry'; key: string } | null>(null)
const customIcons = ref<Array<{ label: string; value: string; svg: string }>>([])
const svgText = ref('')
const groupEditorVisible = ref(false)
const groupDraft = ref({ label: '', iconKey: 'grid', iconSvg: '' })
const savedSnapshot = ref('')

function defaultCategoryIconKey(categoryKey: string) {
  return ({ content: 'create', external: 'globe', internal: 'library', systems: 'server' } as Record<string, string>)[categoryKey] || 'grid'
}

const entryGroups = computed(() => {
  if (!plan.value) return []
  return plan.value.groups.map(group => ({
    ...group,
    iconKey: group.iconKey || defaultCategoryIconKey(group.key),
    iconSvg: group.iconSvg || '',
    entries: plan.value!.entries.filter(entry => entry.categoryKey === group.key),
  }))
})

const currentSnapshot = computed(() => JSON.stringify({ plan: plan.value, customIcons: customIcons.value }))
const hasUnsavedChanges = computed(() => !!plan.value && !!savedSnapshot.value && currentSnapshot.value !== savedSnapshot.value)

defineExpose({ hasUnsavedChanges, save })

onMounted(load)

async function load() {
  loading.value = true
  try {
    const result = await fetchShortcutPlan()
    if (!result.groups?.length) {
      const seen = new Map<string, ShortcutGroup>()
      for (const entry of result.entries) {
        if (!seen.has(entry.categoryKey)) seen.set(entry.categoryKey, { key: entry.categoryKey, label: entry.categoryLabel, iconKey: entry.categoryIconKey || defaultCategoryIconKey(entry.categoryKey), iconSvg: entry.categoryIconSvg || '' })
      }
      result.groups = [...seen.values()].slice(0, 6)
    }
    // Older saves kept custom group SVG only on entries; promote it to the group
    // so new entries and the user client inherit the same icon.
    result.groups = result.groups.map(group => {
      // Promote legacy entry-level locks to the enclosing group once.
      group.locked = !!group.locked || result.entries.some(entry => entry.categoryKey === group.key && entry.locked)
      if (group.iconSvg) return group
      const inheritedSvg = result.entries.find(entry => entry.categoryKey === group.key && entry.categoryIconSvg)?.categoryIconSvg || ''
      return inheritedSvg ? { ...group, iconSvg: inheritedSvg, iconKey: 'grid' } : group
    })
    customIcons.value = result.customIcons || []
    plan.value = result
    savedSnapshot.value = currentSnapshot.value
  }
  catch (error: any) { message.error(error?.response?.data?.detail || t('快捷入口方案加载失败')) }
  finally { loading.value = false }
}

function handleBeforeUnload(event: BeforeUnloadEvent) {
  if (!hasUnsavedChanges.value) return
  event.preventDefault()
  event.returnValue = ''
}

function move(group: { entries: ShortcutEntry[] }, index: number, offset: number) {
  if (!plan.value) return
  const target = index + offset
  if (target < 0 || target >= group.entries.length) return
  const current = group.entries[index]
  const nextEntry = group.entries[target]
  const next = [...plan.value.entries]
  const currentIndex = next.findIndex(item => item.id === current.id)
  const targetIndex = next.findIndex(item => item.id === nextEntry.id)
  if (currentIndex < 0 || targetIndex < 0) return
  ;[next[currentIndex], next[targetIndex]] = [next[targetIndex], next[currentIndex]]
  plan.value.entries = next
}

function moveGroup(index: number, offset: number) {
  if (!plan.value) return
  const target = index + offset
  if (target < 0 || target >= plan.value.groups.length) return
  const groups = [...plan.value.groups]
  ;[groups[index], groups[target]] = [groups[target], groups[index]]
  const groupOrder = new Map(groups.map((group, position) => [group.key, position]))
  plan.value.groups = groups
  plan.value.entries = [...plan.value.entries].sort((left, right) => {
    const groupDelta = (groupOrder.get(left.categoryKey) ?? 999) - (groupOrder.get(right.categoryKey) ?? 999)
    return groupDelta || 0
  })
}

function setGroupLocked(groupKey: string, locked: boolean) {
  const group = plan.value?.groups.find(item => item.key === groupKey)
  if (group) group.locked = locked
}

function updateGroupLabel(groupKey: string, value: string) {
  groupDraftLabels.value = { ...groupDraftLabels.value, [groupKey]: value }
}

function renameGroup(group: { key: string; label: string }) {
  if (!plan.value) return
  const label = (groupDraftLabels.value[group.key] ?? group.label).trim()
  if (!label) {
    groupDraftLabels.value = { ...groupDraftLabels.value, [group.key]: group.label }
    return
  }
  const target = plan.value.groups.find(item => item.key === group.key)
  if (target) target.label = label
  plan.value.entries = plan.value.entries.map(entry => (
    entry.categoryKey === group.key ? { ...entry, categoryLabel: label } : entry
  ))
  const nextDrafts = { ...groupDraftLabels.value }
  delete nextDrafts[group.key]
  groupDraftLabels.value = nextDrafts
}

function updateGroupIcon(group: { key: string }, key: string, svg = '') {
  if (!plan.value) return
  const target = plan.value.groups.find(item => item.key === group.key)
  if (target) {
    target.iconKey = key
    target.iconSvg = svg
  }
  plan.value.entries = plan.value.entries.map(entry => entry.categoryKey === group.key ? { ...entry, categoryIconKey: key, categoryIconSvg: svg } : entry)
}

function updateEntryIcon(entry: ShortcutEntry, key: string) {
  entry.iconKey = key
  entry.iconSvg = ''
}

function moveEntryToGroup(entry: ShortcutEntry, groupKey: string) {
  if (!plan.value || entry.categoryKey === groupKey) return
  const target = plan.value.groups.find(group => group.key === groupKey)
  if (!target) return
  if (plan.value.entries.filter(item => item.categoryKey === groupKey).length >= 6) {
    message.warning(t('每个分组最多 6 个入口'))
    return
  }
  Object.assign(entry, {
    categoryKey: target.key,
    categoryLabel: target.label,
    categoryIconKey: target.iconKey,
    categoryIconSvg: target.iconSvg || '',
  })
}

function openGroupIconPicker(group: { key: string }) {
  iconPickerTarget.value = { kind: 'group', key: group.key }
  svgText.value = ''
  iconPickerVisible.value = true
}

function openGroupEditor() {
  if (!plan.value || plan.value.groups.length >= 6) {
    message.warning(t('最多创建 6 个分组，请先删除现有分组'))
    return
  }
  groupDraft.value = { label: '', iconKey: 'grid', iconSvg: '' }
  groupEditorVisible.value = true
}

function createGroup() {
  if (!plan.value || !groupDraft.value.label.trim() || plan.value.groups.length >= 6) return
  const key = `custom.${Date.now()}`
  const group: ShortcutGroup = { key, label: groupDraft.value.label.trim(), iconKey: groupDraft.value.iconKey, iconSvg: groupDraft.value.iconSvg, locked: false }
  plan.value.groups = [...plan.value.groups, group]
  groupEditorVisible.value = false
}

function removeGroup(group: { key: string; entries: ShortcutEntry[] }) {
  if (!plan.value || group.entries.length) {
    message.warning(t('请先将分组内入口移动到其他分组'))
    return
  }
  plan.value.groups = plan.value.groups.filter(item => item.key !== group.key)
}

function openEntryIconPicker(entry: ShortcutEntry) {
  iconPickerTarget.value = { kind: 'entry', key: entry.id }
  svgText.value = ''
  iconPickerVisible.value = true
}

function selectIcon(icon: { value: string; svg: string }) {
  if (!plan.value || !iconPickerTarget.value) return
  if (iconPickerTarget.value.kind === 'group') {
    if (iconPickerTarget.value.key === '__new__') {
      groupDraft.value.iconKey = icon.value.startsWith('custom.') ? 'grid' : icon.value
      groupDraft.value.iconSvg = icon.value.startsWith('custom.') ? icon.svg : ''
      iconPickerVisible.value = false
      return
    }
    const customSvg = icon.value.startsWith('custom.') ? icon.svg : ''
    updateGroupIcon({ key: iconPickerTarget.value.key }, customSvg ? 'grid' : icon.value, customSvg)
  } else {
    const entry = plan.value.entries.find(item => item.id === iconPickerTarget.value?.key)
    if (entry) { entry.iconKey = icon.value.startsWith('custom.') ? 'document' : icon.value; entry.iconSvg = icon.value.startsWith('custom.') ? icon.svg : '' }
  }
  iconPickerVisible.value = false
}

function handleIconUpload(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file) return
  const reader = new FileReader()
  reader.onload = () => {
    const content = String(reader.result || '').trim()
    applyCustomSvg(content, file.name)
  }
  reader.readAsText(file)
  ;(event.target as HTMLInputElement).value = ''
}

function applyCustomSvg(content: string, label: string) {
  const start = content.search(/<svg\b/i)
  const end = content.toLowerCase().lastIndexOf('</svg>')
  const svg = start >= 0 && end > start ? content.slice(start, end + 6).trim() : ''
  if (!svg || /<script\b|<foreignobject\b|\son[a-z]+\s*=|javascript:/i.test(svg)) {
    message.error(t('SVG 图标格式不安全'))
    return
  }
  const icon = { label, value: `custom.${Date.now()}`, svg }
  customIcons.value = [...customIcons.value, icon]
  selectIcon(icon)
  svgText.value = ''
}

function removeCustomIcon(value: string) {
  customIcons.value = customIcons.value.filter(icon => icon.value !== value)
}

function applySvgText() {
  const content = svgText.value.trim()
  if (!content) return
  applyCustomSvg(content, t('粘贴的 SVG'))
}

function toggleGroup(groupKey: string) {
  const next = new Set(collapsedGroups.value)
  if (next.has(groupKey)) next.delete(groupKey)
  else next.add(groupKey)
  collapsedGroups.value = next
}

function remove(entry: ShortcutEntry) {
  if (!plan.value) return
  plan.value.entries = plan.value.entries.filter(item => item.id !== entry.id)
}

function saveEntry() {
  if (!plan.value || !draft.value.label.trim() || (draft.value.type === 'skill' && !draft.value.resourceId) || (draft.value.type !== 'skill' && !draft.value.prompt.trim())) return
  if (editingEntryId.value) {
    const entry = plan.value.entries.find(item => item.id === editingEntryId.value)
    if (entry) {
      if (entry.categoryKey !== draft.value.groupKey && plan.value.entries.filter(item => item.categoryKey === draft.value.groupKey).length >= 6) {
        message.warning(t('每个分组最多 6 个入口'))
        return
      }
      entry.label = draft.value.label.trim()
      entry.type = draft.value.type
      entry.resourceId = draft.value.resourceId
      entry.prompt = draft.value.prompt.trim() || `请使用 Skill「${entry.label}」完成以下任务：`
      moveEntryToGroup(entry, draft.value.groupKey)
    }
    editingEntryId.value = null
    editorVisible.value = false
    return
  }
  const group = plan.value.groups.find(item => item.key === draft.value.groupKey) || plan.value.groups[0]
  if (!group) return
  if (plan.value.entries.filter(entry => entry.categoryKey === group.key).length >= 6) {
    message.warning(t('每个分组最多 6 个入口'))
    editorVisible.value = false
    return
  }
  const id = `custom.${Date.now()}`
  plan.value.entries.push({
    id,
    type: draft.value.type,
    categoryKey: group.key,
    categoryLabel: group.label,
    label: draft.value.label.trim(),
    iconKey: draft.value.type === 'skill' ? 'build' : 'document',
    categoryIconKey: group.iconKey,
    categoryIconSvg: group.iconSvg || '',
    prompt: draft.value.prompt.trim() || `请使用 Skill「${draft.value.label.trim()}」完成以下任务：`,
    resourceId: draft.value.resourceId,
    enabled: true,
    locked: false,
  })
  draft.value = { type: 'prompt', label: '', prompt: '', groupKey: plan.value.groups[0]?.key || '', resourceId: '' }
  editorVisible.value = false
}

function openPromptEditor(groupKey?: string) {
  if (!plan.value) return
  const targetGroup = plan.value.groups.find(group => group.key === groupKey) || plan.value.groups[0]
  if (!targetGroup) return
  if (plan.value.entries.filter(entry => entry.categoryKey === targetGroup.key).length >= 6) {
    message.warning(t('每个分组最多 6 个入口'))
    return
  }
  editingEntryId.value = null
  draft.value = { type: 'prompt', label: '', prompt: '', groupKey: targetGroup.key, resourceId: '' }
  editorVisible.value = true
  void loadSkillOptions()
}

function openEntryEditor(entry: ShortcutEntry) {
  editingEntryId.value = entry.id
  draft.value = { type: entry.type, label: entry.label, prompt: entry.prompt || '', groupKey: entry.categoryKey, resourceId: entry.resourceId || '' }
  editorVisible.value = true
  void loadSkillOptions()
}

async function loadSkillOptions() {
  skillLoading.value = true
  try {
    const skills = await fetchSkills()
    skillOptions.value = skills.filter(skill => skill.enabled)
  } catch {
    skillOptions.value = []
  } finally {
    skillLoading.value = false
  }
}

function selectSkill(skillId: string) {
  const skill = skillOptions.value.find(item => item.id === skillId)
  if (skill) {
    draft.value.resourceId = skill.id
    draft.value.label = skill.name
  }
}

async function save() {
  if (!plan.value) return
  saving.value = true
  try {
    plan.value = await saveShortcutPlan({
      name: plan.value.name,
      groups: plan.value.groups,
      customIcons: customIcons.value,
      entries: plan.value.entries.map(entry => ({
        ...entry,
        locked: false,
        categoryIconKey: entry.categoryIconKey || defaultCategoryIconKey(entry.categoryKey),
        iconSvg: entry.iconSvg || '',
        categoryIconSvg: entry.categoryIconSvg || '',
      })),
    })
    message.success(t('快捷入口方案已保存'))
    savedSnapshot.value = currentSnapshot.value
  } catch (error: any) {
    message.error(error?.response?.data?.detail || t('快捷入口方案保存失败'))
  } finally { saving.value = false }
}

onMounted(() => window.addEventListener('beforeunload', handleBeforeUnload))
onBeforeUnmount(() => window.removeEventListener('beforeunload', handleBeforeUnload))
</script>

<template>
  <div class="shortcut-settings">
    <div class="settings-header shortcut-settings-header">
      <div class="shortcut-header-copy">
        <div class="settings-title">{{ t('快捷入口方案') }}</div>
        <div class="settings-subtitle">{{ t('配置所有员工默认看到的快捷入口；未锁定分组允许员工调整组内顺序。') }}</div>
      </div>
      <n-space>
        <n-button secondary @click="openGroupEditor">
          <template #icon><ShortcutActionIcon kind="add" /></template>
          {{ t('新建分组') }}
        </n-button>
        <n-button type="primary" :loading="saving" :disabled="!hasUnsavedChanges" @click="save">
          <template #icon><ShortcutActionIcon kind="save" /></template>
          {{ hasUnsavedChanges ? t('保存配置') : t('已保存') }}
        </n-button>
      </n-space>
    </div>

    <n-alert type="info" :bordered="false">{{ t('锁定分组后，员工不能调整该分组及其中的入口；快捷入口不会改变 Skill 本身的权限。') }}</n-alert>
    <n-spin :show="loading">
      <div v-if="plan" class="group-list">
        <section v-for="(group, groupIndex) in entryGroups" :key="group.key" class="entry-group">
          <header class="group-header">
            <div class="group-title">
              <button type="button" class="icon-picker-trigger" :aria-label="t('选择分组图标')" @click="openGroupIconPicker(group)">
                <span v-html="group.iconSvg || shortcutIconCatalog.find(icon => icon.value === group.iconKey)?.svg" />
              </button>
              <n-input
                :value="groupDraftLabels[group.key] ?? group.label"
                size="small"
                :aria-label="t('分组名称')"
                @update:value="(value: string) => updateGroupLabel(group.key, value)"
                @blur="() => renameGroup(group)"
              />
              <span>{{ t('共 {count} 个入口', { count: group.entries.length }) }}</span>
            </div>
            <div class="group-controls">
              <n-button secondary size="small" @click="openPromptEditor(group.key)">{{ t('添加入口') }}</n-button>
              <label class="entry-switch"><span>{{ t('锁定分组') }}</span><n-switch :value="!!group.locked" size="small" @update:value="(value: boolean) => setGroupLocked(group.key, value)" /></label>
              <n-button quaternary type="error" size="small" :disabled="group.entries.length > 0" @click="removeGroup(group)">{{ t('删除分组') }}</n-button>
              <div class="group-order-actions">
                <n-button quaternary size="tiny" :disabled="groupIndex === 0" :aria-label="t('分组上移')" @click="moveGroup(groupIndex, -1)">↑</n-button>
                <n-button quaternary size="tiny" :disabled="groupIndex === entryGroups.length - 1" :aria-label="t('分组下移')" @click="moveGroup(groupIndex, 1)">↓</n-button>
              </div>
            </div>
            <n-button
              quaternary
              size="small"
              class="group-toggle"
              :aria-label="collapsedGroups.has(group.key) ? t('展开分组') : t('收起分组')"
              :aria-expanded="!collapsedGroups.has(group.key)"
              @click="toggleGroup(group.key)"
            >
              <ShortcutGroupToggleIcon class="group-toggle-icon" :class="{ collapsed: collapsedGroups.has(group.key) }" />
            </n-button>
          </header>
          <template v-if="!collapsedGroups.has(group.key)">
            <article v-for="(entry, index) in group.entries" :key="entry.id" class="entry-row">
            <div class="entry-order">
              <n-button quaternary size="tiny" :disabled="index === 0" @click="move(group, index, -1)">↑</n-button>
              <n-button quaternary size="tiny" :disabled="index === group.entries.length - 1" @click="move(group, index, 1)">↓</n-button>
            </div>
            <div class="entry-main">
              <strong>{{ t(entry.label) }}</strong>
              <span>{{ entry.type === 'prompt' ? 'Prompt' : entry.type === 'skill' ? 'Skill' : 'Agent' }}</span>
            </div>
            <button type="button" class="icon-picker-trigger entry-icon-trigger" :aria-label="t('选择入口图标')" @click="openEntryIconPicker(entry)">
              <span v-html="entry.iconSvg || shortcutIconCatalog.find(icon => icon.value === entry.iconKey)?.svg" />
            </button>
            <n-select :value="entry.categoryKey" size="small" class="entry-group-select" :options="plan.groups.map(item => ({ label: item.label, value: item.key }))" @update:value="(value: string) => moveEntryToGroup(entry, value)" />
            <label class="entry-switch"><span>{{ t('展示') }}</span><n-switch v-model:value="entry.enabled" size="small" /></label>
            <n-button quaternary size="small" @click="openEntryEditor(entry)">{{ t('编辑') }}</n-button>
            <n-button quaternary type="error" size="small" @click="remove(entry)">{{ t('删除') }}</n-button>
            </article>
          </template>
        </section>
      </div>
    </n-spin>

    <n-modal v-model:show="groupEditorVisible" preset="card" :title="t('新建分组')" style="width: min(460px, calc(100vw - 32px))">
      <n-form label-placement="top">
        <n-form-item :label="t('分组名称')" required><n-input v-model:value="groupDraft.label" :placeholder="t('请输入分组名称')" /></n-form-item>
        <n-form-item :label="t('分组图标')">
          <button type="button" class="icon-picker-trigger" :aria-label="t('选择分组图标')" @click="iconPickerTarget = { kind: 'group', key: '__new__' }; iconPickerVisible = true">
            <span v-html="shortcutIconCatalog.find(icon => icon.value === groupDraft.iconKey)?.svg" />
          </button>
        </n-form-item>
      </n-form>
      <template #footer><n-space justify="end"><n-button @click="groupEditorVisible = false">{{ t('取消') }}
      </n-button><n-button type="primary" @click="createGroup">{{ t('创建') }}
      </n-button></n-space></template>
    </n-modal>

    <n-modal v-model:show="iconPickerVisible" preset="card" :title="t('选择图标')" style="width: min(560px, calc(100vw - 32px))">
      <div class="icon-picker-grid">
        <button v-for="icon in [...shortcutIconCatalog, ...customIcons]" :key="icon.value" type="button" class="icon-option" @click="selectIcon(icon)">
          <span v-html="icon.svg" />
          <small>{{ icon.label }}</small>
          <span
            v-if="icon.value.startsWith('custom.')"
            class="icon-delete"
            role="button"
            tabindex="0"
            :aria-label="t('删除自定义图标')"
            @click.stop="removeCustomIcon(icon.value)"
            @keydown.enter.stop="removeCustomIcon(icon.value)"
          >×</span>
        </button>
        <label class="icon-option icon-upload-option">
          <input type="file" accept=".svg,image/svg+xml" @change="handleIconUpload" />
          <span class="upload-plus">＋</span>
          <small>{{ t('上传 SVG') }}</small>
        </label>
      </div>
      <div class="svg-code-panel">
        <n-input v-model:value="svgText" type="textarea" :rows="3" :placeholder="t('粘贴 SVG 代码')" />
        <n-button type="primary" size="small" :disabled="!svgText.trim()" @click="applySvgText">{{ t('使用 SVG 代码') }}</n-button>
      </div>
    </n-modal>

    <n-modal v-model:show="editorVisible" preset="card" :title="t(editingEntryId ? '编辑快捷入口' : '新增快捷入口')" style="width: min(560px, calc(100vw - 32px))">
      <n-form label-placement="top">
        <n-form-item :label="t('入口类型')" required>
          <n-select v-model:value="draft.type" :options="[{ label: 'Prompt', value: 'prompt' }, { label: 'Skill', value: 'skill' }]" />
        </n-form-item>
        <n-form-item v-if="draft.type === 'skill'" :label="t('选择 Skill')" required>
          <n-select :value="draft.resourceId || null" :options="skillOptions.map(skill => ({ label: skill.name, value: skill.id }))" :loading="skillLoading" filterable @update:value="selectSkill" />
        </n-form-item>
        <n-form-item :label="t('入口名称')" required><n-input v-model:value="draft.label" /></n-form-item>
        <n-form-item :label="t('所属分组')" required><n-select v-model:value="draft.groupKey" :options="plan?.groups.map(item => ({ label: item.label, value: item.key })) || []" /></n-form-item>
        <n-form-item v-if="draft.type === 'prompt'" :label="t('Prompt 内容')" required><n-input v-model:value="draft.prompt" type="textarea" :rows="5" /></n-form-item>
      </n-form>
      <template #footer><n-space justify="end"><n-button @click="editorVisible = false">{{ t('取消') }}</n-button><n-button type="primary" @click="saveEntry">{{ t(editingEntryId ? '保存修改' : '添加') }}</n-button></n-space></template>
    </n-modal>
  </div>
</template>

<style scoped>
.shortcut-settings { display: grid; gap: 16px; }
.settings-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.shortcut-settings-header { position: sticky; top: -22px; z-index: 20; margin: -22px -22px 0; padding: 14px 22px 12px; border-bottom: 1px solid #e6ebf2; background: rgba(255,255,255,.98); box-shadow: 0 4px 12px rgba(30, 55, 90, .05); backdrop-filter: blur(8px); }
.shortcut-header-copy { min-width: 0; }
.settings-title { color: #182236; font-size: 20px; font-weight: 700; }
.settings-subtitle, .summary { margin-top: 6px; color: #7b8799; font-size: 13px; }
.group-list { display: grid; gap: 14px; }
.entry-group { overflow: hidden; border: 1px solid #e5eaf2; border-radius: 14px; background: #fff; }
.group-header { display: flex; align-items: center; gap: 12px; padding: 12px 16px; border-bottom: 1px solid #edf1f6; background: #f8faff; flex-wrap: wrap; }
.group-title { display: flex; min-width: 220px; flex: 1; align-items: center; gap: 10px; }
.group-controls { display: flex; align-items: center; gap: 8px; margin-left: auto; }
.group-title :deep(.n-input) { max-width: 240px; }
.group-title > span { color: #8a96a8; font-size: 12px; white-space: nowrap; }
.icon-picker-trigger { display: inline-flex; width: 32px; height: 32px; align-items: center; justify-content: center; padding: 6px; border: 1px solid #dce4ef; border-radius: 8px; color: #3867d6; background: #fff; cursor: pointer; }
.icon-picker-trigger:hover { border-color: #4b7bec; background: #f4f7ff; }
.icon-picker-trigger :deep(svg) { width: 18px; height: 18px; }
.group-toggle { min-width: 28px; }
.group-order-actions { display: flex; gap: 2px; }
.group-toggle-icon { display: block; width: 16px; height: 16px; transition: transform .18s ease; }
.group-toggle-icon.collapsed { transform: rotate(-90deg); }
.entry-row { display: flex; min-height: 62px; align-items: center; gap: 10px; padding: 9px 16px; border-bottom: 1px solid #edf1f6; }
.entry-row:hover { background: #fbfcff; }
.entry-group .entry-row:last-child { border-bottom: 0; }
.entry-order { display: flex; gap: 2px; }
.entry-main { display: grid; min-width: 0; flex: 1; gap: 4px; }
.entry-main strong { color: #26344a; font-size: 14px; }
.entry-main span { color: #8a96a8; font-size: 12px; }
.entry-icon-trigger { flex: 0 0 auto; }
.entry-group-select { width: 150px; }
.icon-picker-grid { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 10px; }
.icon-option { position: relative; display: flex; min-height: 70px; flex-direction: column; align-items: center; justify-content: center; gap: 7px; border: 1px solid #e2e8f0; border-radius: 10px; color: #52627a; background: #fff; cursor: pointer; }
.icon-option:hover { border-color: #4b7bec; color: #3867d6; background: #f4f7ff; }
.icon-option :deep(svg) { width: 24px; height: 24px; }
.icon-option small { overflow: hidden; max-width: 100%; padding: 0 4px; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.icon-delete { position: absolute; top: 3px; right: 6px; color: #a0aabd; font-size: 16px; line-height: 16px; }
.icon-delete:hover { color: #d03050; }
.icon-upload-option input { display: none; }
.upload-plus { font-size: 26px; line-height: 24px; }
.svg-code-panel { display: grid; gap: 8px; margin-top: 14px; padding-top: 14px; border-top: 1px solid #edf1f6; }
.svg-code-panel .n-button { justify-self: end; }
.entry-switch { display: flex; align-items: center; gap: 7px; color: #667085; font-size: 12px; }
</style>
