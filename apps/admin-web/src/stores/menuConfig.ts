/**
 * 055 菜单管理 —— 覆盖层 store。
 *
 * 设计要点：
 *  - 只存差异；空数组 = 默认菜单，侧边栏首帧就能渲染，不等接口。
 *  - 任何异常（网络/5xx/坏数据）都静默回退默认菜单，不让侧边栏白屏。
 *  - 未知 key / 非法 parentKey / 非法 iconKey 一律丢弃并告警：
 *    静态 appRoutes 才是白名单，配置不能凭空造菜单项。
 */
import { defineStore } from 'pinia';
import {
  fetchMenuPlan,
  resetMenuPlan,
  saveMenuPlan,
  type MenuNodeOverride,
} from '@/api/menu-settings';
import { ICON_REGISTRY, LOCKED_KEYS, menuCatalog } from '@/composables/menuCatalog';

const VALID_LOCALES = new Set(['zh-CN', 'en-US']);

function sanitize(nodes: unknown): MenuNodeOverride[] {
  if (!Array.isArray(nodes)) return [];
  const seen = new Set<string>();
  const result: MenuNodeOverride[] = [];
  for (const raw of nodes) {
    if (!raw || typeof raw !== 'object') continue;
    const item = raw as Record<string, unknown>;
    const key = typeof item.key === 'string' ? item.key : '';
    if (!key || !menuCatalog.knownKeys.has(key)) {
      console.warn('[menuConfig] 丢弃未知菜单节点', key);
      continue;
    }
    if (seen.has(key)) {
      console.warn('[menuConfig] 丢弃重复菜单节点', key);
      continue;
    }
    const parentKey =
      item.parentKey === null || item.parentKey === undefined
        ? null
        : typeof item.parentKey === 'string' && menuCatalog.groupKeys.has(item.parentKey)
          ? item.parentKey
          : null;
    const iconKey =
      typeof item.iconKey === 'string' && ICON_REGISTRY[item.iconKey] ? item.iconKey : null;
    let label: MenuNodeOverride['label'] = null;
    if (item.label && typeof item.label === 'object') {
      const cleaned: Record<string, string> = {};
      for (const [locale, value] of Object.entries(item.label as Record<string, unknown>)) {
        if (VALID_LOCALES.has(locale) && typeof value === 'string' && value.trim()) {
          cleaned[locale] = value.trim().slice(0, 80);
        }
      }
      label = Object.keys(cleaned).length ? cleaned : null;
    }
    const locked = LOCKED_KEYS.has(key) || item.locked === true;
    const visible = locked ? true : item.visible === false ? false : null;
    const order = typeof item.order === 'number' && Number.isFinite(item.order) ? item.order : null;
    seen.add(key);
    result.push({ key, parentKey, label, iconKey, visible, order, locked });
  }
  return result;
}

interface MenuConfigState {
  nodes: MenuNodeOverride[];
  loaded: boolean;
  loading: boolean;
  loadFailed: boolean;
  saving: boolean;
  tenantKey: string;
  updatedAt: string;
}

export const useMenuConfigStore = defineStore('menuConfig', {
  state: (): MenuConfigState => ({
    nodes: [],
    loaded: false,
    loading: false,
    loadFailed: false,
    saving: false,
    tenantKey: '',
    updatedAt: '',
  }),
  getters: {
    overrides: (state): Map<string, MenuNodeOverride> =>
      new Map(state.nodes.map((node) => [node.key, node])),
    isCustomized: (state): boolean => state.nodes.length > 0,
  },
  actions: {
    /** 幂等加载；tenantKey 变化（切租户 / 重新登录）自动失效重载。 */
    async load(tenantKey: string, force = false) {
      if (this.loading) return;
      const tenantChanged = this.tenantKey !== tenantKey;
      if (tenantChanged) {
        this.tenantKey = tenantKey;
        this.loaded = false;
        this.nodes = [];
      }
      if (this.loaded && !force) return;
      this.loading = true;
      try {
        const plan = await fetchMenuPlan();
        this.nodes = sanitize(plan?.nodes);
        this.updatedAt = plan?.updatedAt || '';
        this.loadFailed = false;
      } catch {
        // 静默回退默认菜单：侧边栏不因配置接口故障而消失。
        this.nodes = [];
        this.updatedAt = '';
        this.loadFailed = true;
      } finally {
        this.loaded = true;
        this.loading = false;
      }
    },
    async save(nodes: MenuNodeOverride[]) {
      this.saving = true;
      try {
        const plan = await saveMenuPlan(sanitize(nodes));
        this.nodes = sanitize(plan?.nodes);
        this.updatedAt = plan?.updatedAt || '';
        this.loaded = true;
        this.loadFailed = false;
      } finally {
        this.saving = false;
      }
    },
    async reset() {
      this.saving = true;
      try {
        await resetMenuPlan();
        this.nodes = [];
        this.updatedAt = '';
        this.loaded = true;
        this.loadFailed = false;
      } finally {
        this.saving = false;
      }
    },
    /** 供菜单管理页读取：把当前覆盖层展开成可编辑节点数组。 */
    editableNodes(): MenuNodeOverride[] {
      return this.nodes.map((node) => ({ ...node, label: node.label ? { ...node.label } : null }));
    },
  },
});
