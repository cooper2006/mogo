<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import GitBranchOutline from '@vicons/ionicons5/es/GitBranchOutline'
import AddOutline from '@vicons/ionicons5/es/AddOutline'
import SearchOutline from '@vicons/ionicons5/es/SearchOutline'
import { createDshWorkspaceBranch, listDshWorkspaceBranches, switchDshWorkspaceBranch } from '../../platform'
import type { DshGitBranchRef, DshGitBranchSnapshot, DshWorkspace } from '../../platform/types'

const props = defineProps<{
  workspace: DshWorkspace
  worktree?: boolean
  selectedRef?: string
  modelId?: string
  locale?: 'zh' | 'en'
}>()

const emit = defineEmits<{
  (event: 'select', fullRef: string, branchLabel: string): void
  (event: 'branch-updated', branch: string): void
}>()

const snapshot = ref<DshGitBranchSnapshot | null>(null)
const loading = ref(true)
const busy = ref(false)
const error = ref('')
const filter = ref('')
const creating = ref(false)
const branchName = ref('')

const filtered = computed(() => {
  const query = filter.value.trim().toLowerCase()
  const items = snapshot.value?.branches || []
  return query ? items.filter(item => item.name.toLowerCase().includes(query)) : items
})
const local = computed(() => filtered.value.filter(item => item.kind === 'local'))
const remote = computed(() => filtered.value.filter(item => item.kind === 'remote'))

function readableError(value: unknown): string {
  if (value instanceof Error) return value.message
  if (typeof value === 'string') return value
  try { return JSON.stringify(value) } catch { return String(value) }
}

async function refresh() {
  loading.value = true
  error.value = ''
  try { snapshot.value = await listDshWorkspaceBranches(props.workspace.workspace_id, props.modelId) }
  catch (value) { error.value = readableError(value) }
  finally { loading.value = false }
}

async function selectBranch(branch: DshGitBranchRef) {
  if (busy.value) return
  error.value = ''
  if (props.worktree) {
    emit('select', branch.full_ref, branch.name)
    return
  }
  if (branch.current) {
    emit('select', branch.full_ref, branch.name)
    return
  }
  busy.value = true
  try {
    snapshot.value = await switchDshWorkspaceBranch(props.workspace.workspace_id, branch.full_ref, props.modelId)
    const current = snapshot.value.current_branch
    emit('select', current ? `refs/heads/${current}` : 'HEAD', current)
    emit('branch-updated', current)
  } catch (value) { error.value = readableError(value) }
  finally { busy.value = false }
}

async function createBranch() {
  if (!branchName.value.trim() || busy.value) return
  busy.value = true
  error.value = ''
  try {
    snapshot.value = await createDshWorkspaceBranch(
      props.workspace.workspace_id, branchName.value.trim(), props.selectedRef || 'HEAD', props.modelId,
    )
    const current = snapshot.value.current_branch
    branchName.value = ''
    creating.value = false
    emit('select', current ? `refs/heads/${current}` : 'HEAD', current)
    emit('branch-updated', current)
  } catch (value) { error.value = readableError(value) }
  finally { busy.value = false }
}

onMounted(refresh)
</script>

<template>
  <section class="branch-selector" :aria-busy="loading || busy">
    <header>
      <strong>{{ worktree ? (locale === 'en' ? 'Starting branch' : '起始分支') : (locale === 'en' ? 'Local branch' : '本地分支') }}</strong>
      <span>{{ worktree ? (locale === 'en' ? 'The isolated Worktree starts here; no branch is created yet.' : '隔离目录从此分支启动，暂不创建新分支。') : (locale === 'en' ? 'Switching changes the selected project directory.' : '切换会直接改变当前项目目录。') }}</span>
    </header>
    <label class="branch-search"><SearchOutline /><input v-model="filter" :placeholder="locale === 'en' ? 'Search branches…' : '搜索分支…'" /></label>
    <div v-if="loading" class="branch-state">{{ locale === 'en' ? 'Loading branches…' : '正在读取分支…' }}</div>
    <div v-else class="branch-list">
      <template v-if="local.length">
        <small>{{ locale === 'en' ? 'LOCAL' : '本地' }}</small>
        <button v-for="branch in local" :key="branch.full_ref" type="button" :disabled="busy" :class="{ active: selectedRef === branch.full_ref || (!selectedRef && branch.current) }" @click="selectBranch(branch)">
          <GitBranchOutline /><span>{{ branch.name }}</span><i v-if="branch.current">{{ locale === 'en' ? 'current' : '当前' }}</i>
        </button>
      </template>
      <template v-if="remote.length">
        <small>{{ locale === 'en' ? 'REMOTE' : '远程' }}</small>
        <button v-for="branch in remote" :key="branch.full_ref" type="button" :disabled="busy" :class="{ active: selectedRef === branch.full_ref }" @click="selectBranch(branch)">
          <GitBranchOutline /><span>{{ branch.name }}</span>
        </button>
      </template>
      <div v-if="!local.length && !remote.length" class="branch-state">{{ locale === 'en' ? 'No matching branches' : '没有匹配的分支' }}</div>
    </div>
    <p v-if="error" class="branch-error">{{ error }}</p>
    <div v-if="!worktree" class="branch-create">
      <button v-if="!creating" type="button" class="create-trigger" @click="creating = true"><AddOutline />{{ locale === 'en' ? 'Create local branch' : '新建本地分支' }}</button>
      <form v-else @submit.prevent="createBranch">
        <label for="new-local-branch">{{ locale === 'en' ? 'New branch name' : '新分支名称' }}</label>
        <div><input id="new-local-branch" v-model="branchName" autofocus :disabled="busy" placeholder="feature/example" /><button type="submit" :disabled="busy || !branchName.trim()">{{ locale === 'en' ? 'Create' : '创建' }}</button></div>
      </form>
    </div>
  </section>
</template>

<style scoped>
.branch-selector{border-top: 1px solid var(--mg-border);padding:11px 10px 10px}.branch-selector header{display:flex;flex-direction:column;gap:2px;padding:0 4px 8px}.branch-selector header strong{color: var(--mg-text-1);font-size:12px}.branch-selector header span{color: var(--mg-text-3);font-size:10px;line-height:1.45}.branch-search{display:flex;height:34px;align-items:center;gap:7px;border: 1px solid var(--mg-border);border-radius:8px;background: var(--mg-bg-surface);padding:0 9px;color: var(--mg-text-3)}.branch-search:focus-within{border-color: var(--mg-brand-soft-border);box-shadow:0 0 0 3px #dbeafe80}.branch-search svg{width:14px}.branch-search input{min-width:0;flex:1;border:0;outline:0;background:transparent;color: var(--mg-text-1);font-size:11px}.branch-list{max-height:210px;overflow:auto;padding:7px 0 2px}.branch-list>small{display:block;padding:7px 6px 3px;color: var(--mg-text-3);font-size:9px;font-weight:700;letter-spacing:.06em}.branch-list>button{display:flex;width:100%;min-height:36px;align-items:center;gap:8px;border:0;border-radius:8px;background:transparent;padding:6px 7px;color: var(--mg-text-2);text-align:left;cursor:pointer}.branch-list>button:hover:not(:disabled){background: var(--mg-bg-subtle);color: var(--mg-brand)}.branch-list>button.active{background: var(--mg-info-bg);color: var(--mg-brand)}.branch-list svg{width:15px;flex:none}.branch-list span{min-width:0;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:11px}.branch-list i{color: var(--mg-text-3);font-size:9px;font-style:normal}.branch-state{padding:18px 8px;text-align:center;color: var(--mg-text-3);font-size:10px}.branch-error{margin:7px 2px 0;border-radius:7px;background: var(--mg-danger-bg);padding:7px 8px;color: var(--mg-danger-text);font-size:10px;white-space:pre-wrap}.branch-create{margin-top:7px;border-top: 1px solid var(--mg-border);padding-top:8px}.create-trigger{display:flex;min-height:36px;align-items:center;gap:7px;border:0;border-radius:8px;background:transparent;padding:0 7px;color: var(--mg-brand);font-size:11px;cursor:pointer}.create-trigger:hover{background: var(--mg-info-bg)}.create-trigger svg{width:15px}.branch-create form{padding:2px 4px}.branch-create form>label{display:block;margin-bottom:5px;color: var(--mg-text-3);font-size:10px}.branch-create form>div{display:flex;gap:6px}.branch-create input{min-width:0;height:34px;flex:1;border: 1px solid var(--mg-brand-soft-border);border-radius:8px;padding:0 9px;color: var(--mg-text-1);font-size:11px;outline:0}.branch-create input:focus{border-color: var(--mg-brand-soft-border);box-shadow:0 0 0 3px #dbeafe}.branch-create form button{height:34px;border:0;border-radius:8px;background: var(--mg-brand);padding:0 11px;color: #fff;font-size:11px;font-weight:650;cursor:pointer}.branch-create button:disabled,.branch-list button:disabled{cursor:not-allowed;opacity:.55}:global(html.theme-dark) .branch-selector,:global(html.theme-dark) .branch-create{border-color: var(--mg-border)}:global(html.theme-dark) .branch-selector header strong{color: var(--mg-text-1)}:global(html.theme-dark) .branch-selector header span{color: var(--mg-text-3)}:global(html.theme-dark) .branch-search,:global(html.theme-dark) .branch-create input{border-color: var(--mg-brand-soft-border);background: var(--mg-bg-app);color: var(--mg-text-1)}:global(html.theme-dark) .branch-list>button{color: var(--mg-text-2)}:global(html.theme-dark) .branch-list>button:hover,:global(html.theme-dark) .branch-list>button.active{background: var(--mg-bg-app);color: var(--mg-brand-text)}:global(html.theme-dark) .branch-error{background: var(--mg-danger-bg);color: var(--mg-danger-text)}
</style>
