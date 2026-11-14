/** 055 菜单管理 —— 侧边栏展示覆盖层 API。 */
import { apiClient } from './client';

export interface MenuLabel {
  'zh-CN'?: string;
  'en-US'?: string;
}

export interface MenuNodeOverride {
  key: string;
  parentKey?: string | null;
  label?: MenuLabel | null;
  iconKey?: string | null;
  visible?: boolean | null;
  order?: number | null;
  locked?: boolean;
}

export interface MenuPlan {
  id: string;
  schemeKey: string;
  version: number;
  nodes: MenuNodeOverride[];
  updatedAt: string;
  updatedBy: string;
}

const BASE = '/api/v1/settings/menus';

export async function fetchMenuPlan(): Promise<MenuPlan> {
  const { data } = await apiClient.get<MenuPlan>(BASE);
  return data;
}

export async function saveMenuPlan(nodes: MenuNodeOverride[]): Promise<MenuPlan> {
  const { data } = await apiClient.put<MenuPlan>(BASE, { schemeKey: 'default', nodes });
  return data;
}

export async function resetMenuPlan(): Promise<{ ok: boolean; schemeKey: string }> {
  const { data } = await apiClient.delete<{ ok: boolean; schemeKey: string }>(BASE);
  return data;
}
