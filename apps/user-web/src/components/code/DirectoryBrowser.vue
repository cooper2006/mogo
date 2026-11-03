<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { NButton, NInput, NModal } from 'naive-ui'
import type { DirectoryEntry, DirectoryListing } from '../../api/directories'
import { browseDirectory, createDirectory } from '../../api/directories'

interface Props {
  show: boolean
  authToken?: string | null
  locale?: 'zh' | 'en'
  /** Initial path to browse; null means the workspace root. */
  initialPath?: string | null
  /** Whether the dialog is busy (e.g. project creation in progress). */
  busy?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  locale: 'zh',
  initialPath: null,
  busy: false,
})

const emit = defineEmits<{
  (event: 'select', path: string): void
  (event: 'close'): void
}>()

interface Column {
  listing: DirectoryListing
  selectedEntry: DirectoryEntry | null
}

const columns = ref<Column[]>([])
const loading = ref(false)
const creating = ref(false)
const newName = ref('')
const createError = ref('')
const createParentPath = ref('')

const canCreate = computed(() => {
  const col = columns.value[columns.value.length - 1]
  return Boolean(col && !creating.value && newName.value.trim())
})

async function loadRoot() {
  if (!props.authToken) return
  loading.value = true
  try {
    const listing = await browseDirectory(props.initialPath, props.authToken)
    columns.value = [{ listing, selectedEntry: null }]
  } catch (error: any) {
    console.error('[directory-browser] failed to load root:', error)
    columns.value = []
  } finally {
    loading.value = false
  }
}

async function enterEntry(entry: DirectoryEntry) {
  if (!props.authToken) return
  const col = columns.value[columns.value.length - 1]
  if (!col) return
  // Update the current column's selected entry
  col.selectedEntry = entry
  // Push a new column for the entered directory
  loading.value = true
  try {
    const listing = await browseDirectory(entry.path, props.authToken)
    columns.value.push({ listing, selectedEntry: null })
  } catch (error: any) {
    console.error('[directory-browser] failed to enter directory:', error)
  } finally {
    loading.value = false
  }
}

function goBack() {
  if (columns.value.length <= 1) return
  columns.value.pop()
}

function selectCurrent() {
  const col = columns.value[columns.value.length - 1]
  if (!col) return
  const target = col.selectedEntry
  emit('select', target ? target.path : col.listing.path)
}

function startCreate(parentPath: string) {
  createParentPath.value = parentPath
  newName.value = ''
  createError.value = ''
  creating.value = true
}

async function commitCreate() {
  if (!props.authToken || !creating.value) return
  const name = newName.value.trim()
  if (!name) return
  try {
    const createdPath = await createDirectory(createParentPath.value, name, props.authToken)
    // Refresh the current column
    const col = columns.value[columns.value.length - 1]
    if (col) {
      const listing = await browseDirectory(col.listing.path, props.authToken)
      col.listing = listing
    }
    newName.value = ''
    createError.value = ''
  } catch (error: any) {
    createError.value = error?.message || String(error)
  } finally {
    creating.value = false
  }
}

function cancelCreate() {
  creating.value = false
  newName.value = ''
  createError.value = ''
}

watch(() => props.show, (visible) => {
  if (visible) {
    loadRoot()
  } else {
    columns.value = []
  }
}, { immediate: true })
</script>

<template>
  <NModal
    :show="show"
    preset="card"
    :mask-closable="!busy && !creating"
    :closable="!busy && !creating"
    style="width: 90vw; max-width: 1100px; height: 80vh"
    :title="locale === 'en' ? 'Select project directory' : '选择项目目录'"
    @update:show="(value) => !value && emit('close')"
  >
    <div class="directory-browser">
      <!-- Breadcrumb bar -->
      <div v-if="columns.length" class="crumb-bar">
        <template v-for="(col, idx) in columns" :key="idx">
          <button
            v-if="idx > 0"
            class="crumb-separator"
            aria-label="separator"
          >›</button>
          <button
            class="crumb"
            :class="{ 'crumb-active': idx === columns.length - 1 }"
            :title="col.listing.path"
            @click="columns = columns.slice(0, idx + 1)"
          >
            {{ idx === 0 ? (locale === 'en' ? 'Root' : '根目录') : col.listing.entries.find(e => e.path === col.selectedEntry?.path)?.name || col.selectedEntry?.name || '…' }}
          </button>
        </template>
      </div>

      <!-- Miller columns -->
      <div class="columns-container">
        <div
          v-for="(col, idx) in columns"
          :key="idx"
          class="column"
          :class="{ 'column-active': idx === columns.length - 1 }"
        >
          <div class="column-header">
            <span class="column-title" :title="col.listing.path">
              {{ idx === 0 ? (locale === 'en' ? 'Root' : '根目录') : (col.selectedEntry?.name || (locale === 'en' ? 'Folder' : '文件夹')) }}
            </span>
            <button
              v-if="idx === columns.length - 1"
              class="new-folder-btn"
              :disabled="creating"
              :title="locale === 'en' ? 'New folder' : '新建文件夹'"
              @click="startCreate(col.listing.path)"
            >+</button>
          </div>
          <div class="column-entries">
            <div v-if="loading && idx === columns.length - 1" class="column-loading">
              <span class="dot"></span><span class="dot"></span><span class="dot"></span>
            </div>
            <ul v-else class="entry-list">
              <li
                v-for="entry in col.listing.entries"
                :key="entry.path"
                class="entry"
                :class="{ 'entry-selected': col.selectedEntry?.path === entry.path }"
                @click="enterEntry(entry)"
                @dblclick="enterEntry(entry)"
              >
                <span class="entry-icon">📁</span>
                <span class="entry-name" :title="entry.name">{{ entry.name }}</span>
              </li>
              <li v-if="col.listing.entries.length === 0 && !loading" class="entry-empty">
                {{ locale === 'en' ? 'Empty directory' : '空目录' }}
              </li>
            </ul>
          </div>
          <!-- Inline create form -->
          <div v-if="creating && idx === columns.length - 1" class="create-form">
            <n-input
              v-model:value="newName"
              :placeholder="locale === 'en' ? 'Folder name' : '文件夹名称'"
              size="small"
              @keyup.enter="commitCreate"
            />
            <div class="create-actions">
              <NButton size="small" @click="cancelCreate">{{ locale === 'en' ? 'Cancel' : '取消' }}</NButton>
              <NButton size="small" type="primary" :disabled="!newName.trim()" @click="commitCreate">{{ locale === 'en' ? 'Create' : '创建' }}</NButton>
            </div>
            <p v-if="createError" class="create-error">{{ createError }}</p>
          </div>
        </div>
      </div>

      <!-- Footer -->
      <div class="browser-footer">
        <NButton @click="goBack" :disabled="columns.length <= 1">{{ locale === 'en' ? 'Back' : '返回' }}</NButton>
        <div class="footer-right">
          <NButton @click="emit('close')">{{ locale === 'en' ? 'Cancel' : '取消' }}</NButton>
          <NButton type="primary" :disabled="!columns.length" @click="selectCurrent">
            {{ locale === 'en' ? 'Select this folder' : '选择此文件夹' }}
          </NButton>
        </div>
      </div>
    </div>
  </NModal>
</template>

<style scoped>
.directory-browser {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 400px;
}

.crumb-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 2px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--mg-border);
  font-size: 12px;
  background: var(--mg-bg-subtle);
}

.crumb {
  background: none;
  border: none;
  color: var(--mg-text-2);
  cursor: pointer;
  padding: 2px 4px;
  border-radius: 4px;
  font-size: 12px;
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.crumb:hover {
  background: var(--mg-hover-bg);
  color: var(--mg-text-1);
}

.crumb-active {
  color: var(--mg-text-1);
  font-weight: 600;
  cursor: default;
}

.crumb-separator {
  background: none;
  border: none;
  color: var(--mg-text-3);
  cursor: default;
  padding: 0 2px;
}

.columns-container {
  display: flex;
  flex: 1;
  overflow: hidden;
  min-height: 0;
}

.column {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 220px;
  max-width: 320px;
  border-right: 1px solid var(--mg-border);
  overflow: hidden;
}

.column:last-child {
  border-right: none;
}

.column-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  border-bottom: 1px solid var(--mg-border);
  background: var(--mg-bg-subtle);
}

.column-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--mg-text-1);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
}

.new-folder-btn {
  background: none;
  border: none;
  color: var(--mg-text-3);
  cursor: pointer;
  font-size: 16px;
  width: 24px;
  height: 24px;
  border-radius: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.new-folder-btn:hover:not(:disabled) {
  background: var(--mg-hover-bg);
  color: var(--mg-text-1);
}

.new-folder-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.column-entries {
  flex: 1;
  overflow-y: auto;
  padding: 4px 0;
}

.column-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  padding: 20px;
}

.dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--mg-text-3);
  animation: pulse 1.5s infinite;
}

.dot:nth-child(2) { animation-delay: 0.3s; }
.dot:nth-child(3) { animation-delay: 0.6s; }

@keyframes pulse {
  0%, 100% { opacity: 0.3; }
  50% { opacity: 1; }
}

.entry-list {
  list-style: none;
  margin: 0;
  padding: 0;
}

.entry {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  cursor: pointer;
  font-size: 13px;
  color: var(--mg-text-1);
  border-radius: 4px;
  margin: 1px 4px;
}

.entry:hover {
  background: var(--mg-hover-bg);
}

.entry-selected {
  background: var(--mg-brand-soft-border);
}

.entry-icon {
  font-size: 14px;
  flex-shrink: 0;
}

.entry-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.entry-empty {
  padding: 20px 12px;
  text-align: center;
  color: var(--mg-text-3);
  font-size: 12px;
  list-style: none;
}

.create-form {
  padding: 8px 12px;
  border-top: 1px solid var(--mg-border);
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.create-actions {
  display: flex;
  justify-content: flex-end;
  gap: 6px;
}

.create-error {
  margin: 0;
  font-size: 11px;
  color: var(--n-error-color);
}

.browser-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 12px;
  border-top: 1px solid var(--mg-border);
  background: var(--mg-bg-subtle);
}

.footer-right {
  display: flex;
  gap: 8px;
}
</style>