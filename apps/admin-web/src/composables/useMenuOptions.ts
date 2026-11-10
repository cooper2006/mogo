import type { MenuOption } from 'naive-ui';
import { NIcon } from 'naive-ui';
import { computed, h, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useLocale, t } from '@/composables/i18n';
import {
  menuCatalog,
  menuGroupsFromCatalog,
  resolveIcon,
  type MenuNodeDef,
} from '@/composables/menuCatalog';
import type { MenuNodeOverride } from '@/api/menu-settings';
import { useAuthStore } from '@/stores/auth';
import { useMenuConfigStore } from '@/stores/menuConfig';

type Overrides = Map<string, MenuNodeOverride>;

function renderMenuIcon(icon: unknown) {
  if (typeof icon === 'string') {
    return h('span', { class: 'menu-symbol', 'aria-hidden': 'true' }, icon);
  }
  if (icon) {
    return h(NIcon, { class: 'menu-symbol' }, { default: () => h(icon as any) });
  }
  return null;
}

function effectiveLabel(node: MenuNodeDef, override: MenuNodeOverride | undefined, locale: string): string {
  return override?.label?.[locale as 'zh-CN' | 'en-US']?.trim() || t(node.title);
}

/**
 * 同组内按覆盖层排序；无 order 时保持静态顺序（staticOrder）。
 * 平台管理员只看 platformOnly 项；locked 节点忽略 visible=false。
 */
function orderedSiblings(
  candidates: MenuNodeDef[],
  overrides: Overrides,
  isPlatformAdmin: boolean,
): MenuNodeDef[] {
  return candidates
    .filter((node) => (isPlatformAdmin ? node.platformOnly : !node.platformOnly))
    .filter((node) => node.locked || overrides.get(node.key)?.visible !== false)
    .sort((a, b) => {
      const left = overrides.get(a.key)?.order ?? a.staticOrder;
      const right = overrides.get(b.key)?.order ?? b.staticOrder;
      return left - right || a.staticOrder - b.staticOrder;
    });
}

/** 导出供路由/菜单快照脚本做纯函数断言（不依赖组件上下文）。 */
export function buildOptions(
  isPlatformAdmin: boolean,
  navigate: (path: string) => void,
  overrides: Overrides,
  locale: string,
): MenuOption[] {
  const options: MenuOption[] = [];
  const roots = orderedSiblings(
    menuCatalog.nodes.filter((node) => node.parentKey === null),
    overrides,
    isPlatformAdmin,
  );

  for (const node of roots) {
    const override = overrides.get(node.key);
    const icon = () => renderMenuIcon(resolveIcon(override?.iconKey, node.icon));
    if (!node.isGroup) {
      options.push({
        key: node.key,
        label: effectiveLabel(node, override, locale),
        icon,
      });
      continue;
    }

    const children = orderedSiblings(
      menuCatalog.nodes.filter((item) => item.parentKey === node.key),
      overrides,
      isPlatformAdmin,
    );
    if (!children.length) continue; // 组内全被隐藏时不留空分组

    options.push({
      key: node.key,
      // 一级项本身也是页面：点文字直接跳转，点箭头才展开二级（阻止冒泡避免只展开）。
      // 硬编码分组（组织与用户）没有对应页面，点文字只展开。
      label: node.virtual
        ? effectiveLabel(node, override, locale)
        : () =>
            h(
              'span',
              {
                class: 'menu-group-label',
                onClick: (event: MouseEvent) => {
                  event.stopPropagation();
                  navigate(node.key);
                },
              },
              effectiveLabel(node, override, locale),
            ),
      icon,
      children: children.map((child) => ({
        key: child.key,
        label: effectiveLabel(child, overrides.get(child.key), locale),
      })),
    });
  }

  return options;
}

/** 当前路径应自动展开的一级分组 key（含分组自身页面、子页面及其详情页）。 */
function expandedGroupsForPath(path: string): string[] {
  return menuGroupsFromCatalog()
    .filter((group) => {
      if (path === group.key || path.startsWith(`${group.key}/`)) return true;
      return group.childKeys.some(
        (childKey) => path === childKey || path.startsWith(`${childKey}/`),
      );
    })
    .map((group) => group.key);
}

export function useMenuOptions() {
  const route = useRoute();
  const router = useRouter();
  const { locale } = useLocale();
  const authStore = useAuthStore();
  const menuStore = useMenuConfigStore();

  const tenantKey = computed(() => authStore.profile?.tenantId || '');

  onMounted(() => {
    void menuStore.load(tenantKey.value);
  });

  // 切租户 / 重新登录后配置必须失效重载，避免沿用上个租户的菜单。
  watch(tenantKey, (key) => {
    void menuStore.load(key, true);
  });

  const menuOptions = computed(() => {
    // eslint-disable-next-line @typescript-eslint/no-unused-expressions -- explicit dependency on locale reactive state
    locale.value; // Explicitly depend on locale reactive state
    return buildOptions(
      authStore.isPlatformAdmin,
      (path: string) => router.push(path),
      menuStore.overrides,
      locale.value,
    );
  });

  const expandedKeys = ref<string[]>(expandedGroupsForPath(route.path));

  watch(
    () => route.path,
    (path) => {
      const missing = expandedGroupsForPath(path).filter(
        (key) => !expandedKeys.value.includes(key),
      );
      if (missing.length) expandedKeys.value = [...expandedKeys.value, ...missing];
    },
  );

  return {
    menuOptions,
    selectedKey: computed(() => route.path),
    expandedKeys,
    handleUpdate: (key: string) => {
      router.push(key);
    },
    handleExpandedKeysUpdate: (keys: string[]) => {
      expandedKeys.value = keys;
    },
  };
}
