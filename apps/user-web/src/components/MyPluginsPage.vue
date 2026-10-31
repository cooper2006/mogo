<template>
  <div class="page-stack plugin-workspace">
    <PluginOverview :plugins="rows" />
    <PluginCatalog
      :plugins="rows"
      :loading="loading"
      :busy-id="busyId"
      @reload="reload"
      @add="installOpen = true"
      @toggle="toggle"
      @remove="remove"
      @verify="verify"
    />
    <PluginInstallDialog v-model:show="installOpen" :installing="installing" @install="install" />
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useMessage } from 'naive-ui'
import { t } from '../composables/i18n'
import { installDshPlugin, listDshPlugins, removeDshPlugin, setDshPluginEnabled, uploadDshPlugin, verifyDshPlugin, type DshPlugin } from '../api/dshPlugins'
import PluginOverview from './plugins/PluginOverview.vue'
import PluginCatalog from './plugins/PluginCatalog.vue'
import PluginInstallDialog from './plugins/PluginInstallDialog.vue'

const message = useMessage()
const rows = ref<DshPlugin[]>([])
const loading = ref(false)
const installing = ref(false)
const busyId = ref('')
const installOpen = ref(false)
function errorText(error: unknown): string {
  const detail = (error as any)?.response?.data?.detail
  const messages: Record<string, string> = {
    plugin_package_not_found: 'plugins.installError.notFound',
    plugin_registry_unavailable: 'plugins.installError.registryUnavailable',
    personal_plugin_conflicts_with_restricted_enterprise_plugin: 'plugins.installError.restrictedEnterprise',
    'not-a-bundle': 'plugins.installError.notBundle',
  }
  const key = messages[String(detail)]
  return key ? t(key) : typeof detail === 'string' ? detail : (error as Error)?.message || t('plugins.error')
}

async function reload() {
  loading.value = true
  try { rows.value = await listDshPlugins() }
  catch (error) { message.error(String(errorText(error))) }
  finally { loading.value = false }
}

async function install(source: string | File) {
  if (installing.value) return
  installing.value = true
  try {
    const plugin = typeof source === 'string' ? await installDshPlugin(source) : await uploadDshPlugin(source)
    installOpen.value = false
    const status = plugin.availability?.reason === 'no_global_tool_detected' ? 'unsupported' : plugin.availability?.status
    if (status === 'unsupported') message.warning(t('plugins.installedUnsupported'))
    else if (status === 'session_exposed' || status === 'verified') message.success(t('plugins.installed'))
    else message.warning(t('plugins.installedNeedsCheck'))
    await reload()
  } catch (error) { message.error(String(errorText(error))) }
  finally { installing.value = false }
}

async function verify(plugin: DshPlugin) {
  busyId.value = plugin.id
  try { await verifyDshPlugin(plugin.id); await reload() }
  catch (error) { message.error(String(errorText(error))) }
  finally { busyId.value = '' }
}

async function toggle(plugin: DshPlugin, enabled: boolean) {
  busyId.value = plugin.id
  try { await setDshPluginEnabled(plugin.id, enabled); await reload() }
  catch (error) { message.error(String(errorText(error))) }
  finally { busyId.value = '' }
}

async function remove(plugin: DshPlugin) {
  try { await removeDshPlugin(plugin.id); await reload() }
  catch (error) { message.error(String(errorText(error))) }
}

onMounted(reload)
</script>

<style scoped>
.plugin-workspace {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 12px;
  background: #f6f8fc;
}
</style>
