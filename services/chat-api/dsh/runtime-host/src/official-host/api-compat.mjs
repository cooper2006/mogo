export const DSH_CODE_PRESET_ID = 'code'

const MIGRATED_CODE_PRESET_IDS = new Set(['ptc'])

/** Keep ASKAI's stable `code` contract while DSH evolves preset names. */
export async function resolveNativePreset(presets, requestedPreset) {
  if (requestedPreset !== DSH_CODE_PRESET_ID) return await presets.resolve(requestedPreset)
  try {
    return await presets.resolve(DSH_CODE_PRESET_ID)
  } catch (error) {
    if (error?.code !== 'agent-preset/not-found') throw error
    return await presets.resolve('standard')
  }
}

/** Preserve MOVO's public preset identity across DSH's V2-to-V3 rename. */
export function normalizePersistedPreset(presetId) {
  return MIGRATED_CODE_PRESET_IDS.has(presetId) ? DSH_CODE_PRESET_ID : presetId
}

/** Keep the native permission projection behind MOVO's stable Session contract. */
export function currentPermissionPreset(permissionPresets, session) {
  return permissionPresets.current(session)
}
