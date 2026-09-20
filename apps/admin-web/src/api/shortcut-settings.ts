import { apiClient } from './client'

export type ShortcutEntryType = 'prompt' | 'skill' | 'agent'

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
  enabled: boolean
  locked: boolean
}

export interface ShortcutPlan {
  id: string
  name: string
  entries: ShortcutEntry[]
  groups: ShortcutGroup[]
  customIcons: ShortcutCustomIcon[]
  updatedAt: string
}

export interface ShortcutGroup {
  key: string
  label: string
  iconKey: string
  iconSvg?: string
  locked?: boolean
}

export interface ShortcutCustomIcon {
  label: string
  value: string
  svg: string
}

export async function fetchShortcutPlan(): Promise<ShortcutPlan> {
  const { data } = await apiClient.get<ShortcutPlan>('/api/settings/shortcuts')
  return data
}

export async function saveShortcutPlan(plan: Pick<ShortcutPlan, 'name' | 'entries' | 'groups' | 'customIcons'>): Promise<ShortcutPlan> {
  const { data } = await apiClient.put<ShortcutPlan>('/api/settings/shortcuts', plan)
  return data
}
