/**
 * 055 菜单管理 —— 静态菜单目录（唯一真源）。
 *
 * 侧边栏渲染与「菜单管理」页共用这份由 appRoutes 派生的目录：
 *   - 路由表仍是唯一真源，后端配置只是相对目录的「展示覆盖层」；
 *   - 新增路由会自动出现在菜单里，不需要同步任何配置清单；
 *   - 配置里出现目录外的 key 一律丢弃，不可能凭空造出可访问路由。
 *
 * key 统一使用 route.path（含 /hooks/rules、/token-stats 这类绝对路径子项），
 * 与 useMenuOptions 的 selectedKey 对齐。
 */
import type { RouteRecordRaw } from 'vue-router';
import { appRoutes } from '@/router/routes';
import { AccountGroupsIcon } from '@/icons/AccountGroupsIcon';
import { DashboardBarsIcon } from '@/icons/DashboardBarsIcon';
import { ModelsCenterIcon } from '@/icons/ModelsCenterIcon';
import { KnowledgeDocumentsIcon } from '@/icons/KnowledgeDocumentsIcon';
import { TokenStatsIcon } from '@/icons/TokenStatsIcon';
import { TrafficAllocationIcon } from '@/icons/TrafficAllocationIcon';
import { UserManagementIcon } from '@/icons/UserManagementIcon';
import { ToolsMcpIcon } from '@/icons/ToolsMcpIcon';
import { DshPluginsIcon } from '@/icons/DshPluginsIcon';
import { SkillsManagerIcon } from '@/icons/SkillsManagerIcon';
import { SettingsIcon } from '@/icons/SettingsIcon';
import { PositionRolesIcon } from '@/icons/PositionRolesIcon';
import { SystemAuditIcon } from '@/icons/SystemAuditIcon';
import { HookRulesIcon } from '@/icons/HookRulesIcon';
import { OntologyIcon } from '@/icons/OntologyIcon';
import { ResourceCenterIcon } from '@/icons/ResourceCenterIcon';
import { OrganizationUsersIcon } from '@/icons/OrganizationUsersIcon';

export const ORGANIZATION_GROUP_KEY = '/organizations-group';

/** 图标枚举：与后端 app/menu_settings/catalog.py 的 ICON_KEYS 保持一致。 */
export const ICON_REGISTRY: Record<string, unknown> = {
  dashboard: DashboardBarsIcon,
  models: ModelsCenterIcon,
  knowledge: KnowledgeDocumentsIcon,
  token: TokenStatsIcon,
  traffic: TrafficAllocationIcon,
  users: UserManagementIcon,
  tools: ToolsMcpIcon,
  plugins: DshPluginsIcon,
  skills: SkillsManagerIcon,
  settings: SettingsIcon,
  roles: PositionRolesIcon,
  audit: SystemAuditIcon,
  hooks: HookRulesIcon,
  ontology: OntologyIcon,
  resources: ResourceCenterIcon,
  accounts: AccountGroupsIcon,
  organization: OrganizationUsersIcon,
};

export const ICON_OPTIONS = Object.keys(ICON_REGISTRY).map((value) => ({ label: value, value }));

const ICON_KEY_BY_COMPONENT = new Map<unknown, string>(
  Object.entries(ICON_REGISTRY).map(([key, component]) => [component, key]),
);

/** 不允许隐藏的节点：默认落点、管理入口自身、平台控制台。 */
export const LOCKED_KEYS = new Set(['/dashboard', '/settings/menus', '/platform/tenants']);

export interface MenuNodeDef {
  key: string;
  parentKey: string | null;
  title: string;
  /** 静态图标组件；被 iconKey 覆盖时由 resolveIcon 替换。 */
  icon: unknown;
  iconKey: string | null;
  isGroup: boolean;
  /** 硬编码分组（组织与用户）没有对应页面，点击只展开、不跳转。 */
  virtual?: boolean;
  platformOnly: boolean;
  locked: boolean;
  /** 同组内的静态顺序（0 起），作为 order 覆盖的默认值与排序 tie-break。 */
  staticOrder: number;
}

export interface MenuReadonlyDef {
  key: string;
  title: string;
  kind: 'hidden' | 'redirect';
  target: string;
  platformOnly: boolean;
}

export interface MenuCatalog {
  nodes: MenuNodeDef[];
  readonly: MenuReadonlyDef[];
  knownKeys: Set<string>;
  groupKeys: Set<string>;
}

function joinPath(parent: string, child: string): string {
  if (!child) return parent;
  if (child.startsWith('/')) return child;
  return `${parent.replace(/\/$/, '')}/${child}`;
}

function visibleChildren(route: RouteRecordRaw): RouteRecordRaw[] {
  return ((route.children ?? []) as RouteRecordRaw[]).filter(
    (child) => Boolean(child.meta?.title) && !child.meta?.hideInMenu && child.path !== '',
  );
}

function iconKeyOf(icon: unknown): string | null {
  return ICON_KEY_BY_COMPONENT.get(icon) ?? null;
}

function readonlyEntry(
  route: RouteRecordRaw,
  path: string,
  platformOnly: boolean,
  readonly: MenuReadonlyDef[],
): void {
  const redirect = typeof route.redirect === 'string' ? route.redirect : '';
  readonly.push({
    key: path,
    title: String(route.meta?.title || route.name || '—'),
    kind: redirect ? 'redirect' : 'hidden',
    target: redirect,
    platformOnly,
  });
}

interface NewMenuNode {
  key: string;
  parentKey: string | null;
  title: string;
  icon: unknown;
  isGroup: boolean;
  virtual?: boolean;
  platformOnly: boolean;
}

function buildMenuCatalog(): MenuCatalog {
  const root = appRoutes.find((route) => route.path === '/');
  const children = (root?.children ?? []) as RouteRecordRaw[];
  const nodes: MenuNodeDef[] = [];
  const readonly: MenuReadonlyDef[] = [];
  const groupKeys = new Set<string>();
  const counters = new Map<string, number>();
  let orgGroupAdded = false;

  // 顶层公开页（/login、/setup 等）不参与菜单树，但要在只读清单里可见。
  for (const route of appRoutes) {
    if (route.path === '/') continue;
    readonlyEntry(route, String(route.path), Boolean(route.meta?.platformOnly), readonly);
  }

  const nextOrder = (parentKey: string | null): number => {
    const bucket = parentKey ?? '__root__';
    const value = counters.get(bucket) ?? 0;
    counters.set(bucket, value + 1);
    return value;
  };

  const addNode = (node: NewMenuNode) => {
    nodes.push({
      ...node,
      iconKey: iconKeyOf(node.icon),
      locked: LOCKED_KEYS.has(node.key),
      staticOrder: nextOrder(node.parentKey),
    });
  };

  for (const route of children) {
    const path = String(route.path || '');
    const platformOnly = Boolean(route.meta?.platformOnly);
    if (!path || route.meta?.hideInMenu) {
      readonlyEntry(route, path || '/', platformOnly, readonly);
      continue;
    }

    // 分组优先于 redirect：/resources 既带 redirect 又带 children，
    // 它仍是一级分组（点击落到模型中心），不能误判为只读重定向。
    const subRoutes = visibleChildren(route);
    if (subRoutes.length) {
      groupKeys.add(path);
      addNode({
        key: path,
        parentKey: null,
        title: String(route.meta?.title || route.name || path),
        icon: route.meta?.icon,
        isGroup: true,
        platformOnly,
      });
      for (const child of subRoutes) {
        addNode({
          key: joinPath(path, String(child.path || '')),
          parentKey: path,
          title: String(child.meta?.title || child.name || child.path),
          icon: child.meta?.icon,
          isGroup: false,
          platformOnly: platformOnly || Boolean(child.meta?.platformOnly),
        });
      }
      // 分组里的隐藏子页 / 概览页同样只进只读区。
      for (const child of (route.children ?? []) as RouteRecordRaw[]) {
        if (child.meta?.hideInMenu || child.path === '' || child.redirect) {
          readonlyEntry(
            child,
            child.path === '' ? `${path}/` : joinPath(path, String(child.path || '')),
            platformOnly,
            readonly,
          );
        }
      }
      continue;
    }

    if (route.redirect) {
      readonlyEntry(route, path, platformOnly, readonly);
      continue;
    }

    if (route.meta?.menuGroup === 'organizations') {
      if (!orgGroupAdded) {
        orgGroupAdded = true;
        groupKeys.add(ORGANIZATION_GROUP_KEY);
        addNode({
          key: ORGANIZATION_GROUP_KEY,
          parentKey: null,
          title: '组织与用户',
          icon: OrganizationUsersIcon,
          isGroup: true,
          virtual: true,
          platformOnly: false,
        });
      }
      addNode({
        key: path,
        parentKey: ORGANIZATION_GROUP_KEY,
        title: String(route.meta?.title || route.name || path),
        icon: route.meta?.icon,
        isGroup: false,
        platformOnly,
      });
      continue;
    }

    addNode({
      key: path,
      parentKey: null,
      title: String(route.meta?.title || route.name || path),
      icon: route.meta?.icon,
      isGroup: false,
      platformOnly,
    });
  }

  return {
    nodes,
    readonly,
    knownKeys: new Set(nodes.map((node) => node.key)),
    groupKeys,
  };
}

export const menuCatalog: MenuCatalog = buildMenuCatalog();

/** 覆盖层的 iconKey → 图标组件；非法或空值回退静态图标。 */
export function resolveIcon(iconKey: string | null | undefined, fallback: unknown): unknown {
  if (!iconKey) return fallback;
  return ICON_REGISTRY[iconKey] ?? fallback;
}

/** 用于菜单自动展开：分组 key → 其下所有菜单项 key。 */
export function menuGroupsFromCatalog(): Array<{ key: string; childKeys: string[] }> {
  return menuCatalog.nodes
    .filter((node) => node.isGroup)
    .map((group) => ({
      key: group.key,
      childKeys: menuCatalog.nodes
        .filter((node) => node.parentKey === group.key)
        .map((node) => node.key),
    }));
}
