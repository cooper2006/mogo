import { createApiClient } from './client'

const api = createApiClient({ baseURL: '/askai-api/api', timeout: 30000 })

export type ShortcutEntryType = 'prompt' | 'skill'

export interface ShortcutEntry {
  id: string
  type: ShortcutEntryType
  categoryKey: string
  categoryLabel: string
  label: string
  iconKey: string
  iconSvg?: string
  categoryIconKey?: string
  categoryIconSvg?: string
  prompt: string
  resourceId: string
  enabled?: boolean
  locked?: boolean
  hidden?: boolean
  favorite?: boolean
  personal?: boolean
}

export interface ShortcutPreferences {
  groupOrders: Record<string, string[]>
  personalGroup: ShortcutGroup | null
  personalEntries: ShortcutEntry[]
}

export interface ShortcutGroup {
  key: string
  label: string
  iconKey?: string
  iconSvg?: string
  locked?: boolean
  personal?: boolean
}

export interface EffectiveShortcuts {
  entries: ShortcutEntry[]
  groups: ShortcutGroup[]
  defaultOrder?: string[]
  configured: boolean
  schemeKey?: string
  preferences: ShortcutPreferences
}

export async function fetchEffectiveShortcuts(): Promise<EffectiveShortcuts> {
  const { data } = await api.get('/shortcuts')
  return data?.data as EffectiveShortcuts
}

export async function saveShortcutPreferences(payload: ShortcutPreferences): Promise<EffectiveShortcuts> {
  const { data } = await api.put('/shortcuts/preferences', payload)
  return data?.data as EffectiveShortcuts
}
