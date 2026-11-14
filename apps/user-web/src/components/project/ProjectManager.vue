<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { NButton, NInput, NModal, NForm, NFormItem, useMessage } from 'naive-ui'
import { createDesktopProject, listDesktopProjects, type DesktopProject } from '../../api/sessions'
import { t } from '../../composables/i18n'

const props = defineProps<{
  authToken?: string | null
  canCreate?: boolean
}>()

const emit = defineEmits<{
  (e: 'project-created', project: DesktopProject): void
  (e: 'close'): void
}>()

const message = useMessage()
const loading = ref(false)
const creating = ref(false)
const projects = ref<DesktopProject[]>([])
const projectName = ref('')
const createModalOpen = ref(false)
const createError = ref('')

async function loadProjects() {
  if (!props.authToken) return
  loading.value = true
  try {
    projects.value = await listDesktopProjects(props.authToken)
  } catch (e) {
    message.error(String(e))
  } finally {
    loading.value = false
  }
}

function openCreate() {
  if (!props.canCreate) return
  projectName.value = ''
  createError.value = ''
  createModalOpen.value = true
}

function closeCreate() {
  createModalOpen.value = false
  projectName.value = ''
  createError.value = ''
}

async function commitCreate() {
  if (!props.authToken || creating.value) return
  const title = projectName.value.trim()
  if (!title) {
    createError.value = '请输入项目名称'
    return
  }
  
  // 生成一个唯一的 workspace_id
  const workspaceId = `web-project-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
  
  creating.value = true
  createError.value = ''
  try {
    const project = await createDesktopProject({
      workspace_id: workspaceId,
      title,
      worktree: false,
    }, props.authToken)
    projects.value.unshift(project)
    emit('project-created', project)
    closeCreate()
    message.success('项目创建成功')
  } catch (e) {
    createError.value = String(e)
  } finally {
    creating.value = false
  }
}

onMounted(() => {
  loadProjects()
})
</script>

<template>
  <!-- 项目列表 -->
  <div class="project-manager">
    <div class="project-header">
      <span class="project-title">{{ t('app.project') || '项目' }}</span>
      <NButton 
        v-if="canCreate" 
        size="tiny" 
        type="primary" 
        @click="openCreate"
      >
        {{ t('app.project.create') || '新建项目' }}
      </NButton>
    </div>
    
    <div v-if="loading" class="project-loading">
      <span class="dot"></span><span class="dot"></span><span class="dot"></span>
    </div>
    
    <div v-else-if="projects.length === 0" class="project-empty">
      {{ t('app.project.no_projects') || '暂无项目' }}
    </div>
    
    <div v-else class="project-list">
      <button
        v-for="project in projects"
        :key="project.workspace_id"
        class="project-item"
        type="button"
        :title="project.title"
      >
        <span class="project-icon">📁</span>
        <span class="project-name truncate">{{ project.title }}</span>
        <span v-if="project.status === 'archived'" class="project-status archived">{{ t('app.project.archived') }}</span>
      </button>
    </div>
    
    <!-- 创建项目对话框 -->
    <NModal
      v-model:show="createModalOpen"
      preset="card"
      :mask-closable="!creating"
      :closable="!creating"
      style="width: 420px"
      :title="t('app.project.create') || '创建项目'"
      @update:show="(value) => !value && closeCreate()"
    >
      <div class="create-form">
        <n-form item-layout="vertical">
          <n-form-item :label="t('app.project.name') || '项目名称'">
            <n-input
              v-model:value="projectName"
              :placeholder="t('app.project.name_placeholder') || '请输入项目名称'"
              @keyup.enter="commitCreate"
            />
          </n-form-item>
        </n-form>
        <p v-if="createError" class="error-text">{{ createError }}</p>
      </div>
      <template #footer>
        <div class="dialog-actions">
          <NButton @click="closeCreate">{{ t('ui.cancel') }}</NButton>
          <NButton 
            type="primary" 
            :loading="creating" 
            :disabled="!projectName.trim()"
            @click="commitCreate"
          >
            {{ t('ui.create') || '创建' }}
          </NButton>
        </div>
      </template>
    </NModal>
  </div>
</template>

<style scoped>
.project-manager {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.project-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 4px 0;
}

.project-title {
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--mg-text-3);
}

.project-loading {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 8px;
  font-size: 12px;
  color: var(--mg-text-3);
}

.dot {
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: currentColor;
  animation: pulse 1.5s infinite;
}

.dot:nth-child(2) { animation-delay: 0.3s; }
.dot:nth-child(3) { animation-delay: 0.6s; }

@keyframes pulse {
  0%, 100% { opacity: 0.3; }
  50% { opacity: 1; }
}

.project-empty {
  padding: 12px;
  font-size: 12px;
  color: var(--mg-text-3);
  text-align: center;
}

.project-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.project-item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 6px 8px;
  border: none;
  background: transparent;
  border-radius: 6px;
  cursor: pointer;
  text-align: left;
  font-size: 13px;
  color: var(--mg-text-1);
  transition: background-color 0.15s;
}

.project-item:hover {
  background: var(--mg-hover-bg);
}

.project-icon {
  font-size: 14px;
}

.project-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.project-status {
  font-size: 10px;
  padding: 2px 6px;
  border-radius: 4px;
  background: var(--mg-border);
  color: var(--mg-text-3);
}

.project-status.archived {
  opacity: 0.6;
}

.create-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 8px 0;
}

.error-text {
  color: var(--n-error-color);
  font-size: 12px;
}

.dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
</style>
