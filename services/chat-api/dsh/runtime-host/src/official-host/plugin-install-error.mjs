// Keep the DSH error payload intact enough to diagnose failed installs.
// Its code alone (often "operation-error") does not explain the failure.
export function pluginInstallError(plugin, result) {
  const detail = result.error ?? result
  const description = typeof detail === 'string' ? detail : [
    detail.code,
    detail.diagnostic ?? detail.message ?? detail.reason,
  ].filter(Boolean).join(': ') || JSON.stringify(detail)
  return new Error(`DSH plugin ${plugin.name} failed to install: ${description}`)
}
