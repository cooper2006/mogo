// Keep private service URLs and credentials in the parent Host when a plugin
// Runtime receives a refreshed model or tool credential.
function relayBase(lease) {
  return `http://sandbox-gateway:8101/v1/sandbox-relay/${lease.lease_id}`
}

export function rewritePluginProfile(profile, lease) {
  if (!profile) return profile
  const next = structuredClone(profile)
  const relay = relayBase(lease)
  next.gatewayUrl = `${relay}/model`
  next.accessToken = lease.token
  if (next.toolProfile) {
    next.toolProfile.gatewayUrl = `${relay}/tools`
    next.toolProfile.accessToken = lease.token
  }
  if (next.bundleGatewayUrl) next.bundleGatewayUrl = `${relay}/skill-bundles`
  if (next.pluginGatewayUrl) next.pluginGatewayUrl = `${relay}/plugin-archives`
  return next
}

export function preparePluginCredentialRefresh(entry, kind, credential) {
  if (!entry.profile || typeof credential !== 'object' || credential === null) {
    throw new Error('Plugin Runtime credential is incomplete')
  }
  const profile = structuredClone(entry.profile)
  if (kind === 'model') {
    if (!credential.gatewayUrl || !credential.accessToken) throw new Error('Model credential is incomplete')
    profile.gatewayUrl = credential.gatewayUrl
    profile.accessToken = credential.accessToken
    return {
      profile,
      forwarded: { gatewayUrl: `${relayBase(entry)}/model`, accessToken: entry.token },
    }
  }
  if (kind === 'tool') {
    if (!profile.toolProfile || !credential.accessToken) throw new Error('Tool credential is incomplete')
    profile.toolProfile.accessToken = credential.accessToken
    return { profile, forwarded: { accessToken: entry.token } }
  }
  throw new Error('Unknown plugin credential kind')
}
