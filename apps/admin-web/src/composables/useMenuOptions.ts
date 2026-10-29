import type { MenuOption } from 'naive-ui';
import { NIcon } from 'naive-ui';
import type { RouteRecordRaw } from 'vue-router';
import { computed, h, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { OrganizationUsersIcon } from '@/icons/OrganizationUsersIcon';
import { appRoutes } from '@/router/routes';
import { useAuthStore } from '@/stores/auth';
import { useLocale, t } from '@/composables/i18n';

function renderMenuIcon(icon: unknown) {
  if (typeof icon === 'string') {
    return h(
      'span',
      {
        class: 'menu-symbol',
        'aria-hidden': 'true',
      },
      icon,
    );
  }

  if (icon) {
    return h(
      NIcon,
      {
        class: 'menu-symbol',
      },
      {
        default: () => h(icon as any),
      },
    );
  }

  return null;
}

/** 拼接父子路由路径（child 可能是相对路径或空）。 */
function joinPath(parent: string, child: string): string {
  if (!child) return parent;
  if (child.startsWith('/')) return child;
  return `${parent.replace(/\/$/, '')}/${child}`;
}

/** 取某条路由下需要出现在菜单里的子项（有 title 且未隐藏）。 */
function menuChildren(route: RouteRecordRaw): RouteRecordRaw[] {
  return ((route.children ?? []) as RouteRecordRaw[]).filter(
    (child) => Boolean(child.meta?.title) && !child.meta?.hideInMenu && child.path !== '',
  );
}

/** 所有「分组型」一级菜单的 key（用于自动展开）。 */
function groupKeys(): string[] {
  const root = appRoutes.find((route) => route.path === '/');
  const keys = ((root?.children ?? []) as RouteRecordRaw[])
    .filter((route) => menuChildren(route).length > 0)
    .map((route) => route.path as string);
  // 组织与用户是硬编码分组（由 menuGroup 标记合并而成），不在路由层级里
  return [...keys, '/organizations-group'];
}

function buildOptions(isPlatformAdmin: boolean, navigate: (path: string) => void) {
  const root = appRoutes.find((route) => route.path === '/');
  const children = (root?.children ?? []) as RouteRecordRaw[];
  const visibleRoutes = children.filter((route: RouteRecordRaw) => {
    if (route.meta?.hideInMenu || !route.path) return false;
    // T031: platform-console entries are only meaningful for __platform__; conversely the
    // platform admin only gets the platform console, because tenant business routes are
    // rejected for the reserved identifier (T022 reverse guard).
    if (isPlatformAdmin) return Boolean(route.meta?.platformOnly);
    return !route.meta?.platformOnly;
  });
  const options: MenuOption[] = [];
  let orgMenuAdded = false;

  for (const route of visibleRoutes) {
    const routePath = route.path as string;
    if (route.meta?.menuGroup === 'organizations') {
      if (!orgMenuAdded) {
        orgMenuAdded = true;
        options.push({
          key: '/organizations-group',
          label: t('组织与用户'),
          icon: () =>
            h(
              NIcon,
              {
                class: 'menu-symbol',
              },
              {
                default: () => h(OrganizationUsersIcon),
              },
            ),
          children: [],
        });
      }
      const group = options.find((item) => item.key === '/organizations-group');
      const childrenOptions = ((group?.children as MenuOption[] | undefined) || []);
      childrenOptions.push({
        key: routePath,
        label: t(route.meta?.title as string),
        icon: () => renderMenuIcon(route.meta?.icon),
      });
      if (group) {
        group.children = childrenOptions;
      }
      continue;
    }
    const subRoutes = menuChildren(route);
    if (subRoutes.length) {
      options.push({
        key: routePath,
        // 一级项本身也是页面：点文字直接跳转，点箭头才展开二级（阻止冒泡避免只展开）
        label: () =>
          h(
            'span',
            {
              class: 'menu-group-label',
              onClick: (event: MouseEvent) => {
                event.stopPropagation();
                navigate(routePath);
              },
            },
            t(route.meta?.title as string),
          ),
        icon: () => renderMenuIcon(route.meta?.icon),
        children: subRoutes.map((child) => ({
          key: joinPath(routePath, child.path as string),
          label: t(child.meta?.title as string),
        })),
      });
      continue;
    }

    options.push({
      key: routePath,
      label: t(route.meta?.title as string),
      icon: () => renderMenuIcon(route.meta?.icon),
    });
  }

  return options;
}

export function useMenuOptions() {
  const route = useRoute();
  const router = useRouter();
  const { locale } = useLocale();
  const authStore = useAuthStore();

  const menuOptions = computed(() => {
    // eslint-disable-next-line @typescript-eslint/no-unused-expressions -- explicit dependency on locale reactive state
    locale.value; // Explicitly depend on locale reactive state
    return buildOptions(authStore.isPlatformAdmin, (path: string) => router.push(path));
  });

  const expandedKeys = ref<string[]>(
    groupKeys().filter((key) => route.path === key || route.path.startsWith(`${key}/`)),
  );

  watch(
    () => route.path,
    (path) => {
      for (const key of groupKeys()) {
        if ((path === key || path.startsWith(`${key}/`)) && !expandedKeys.value.includes(key)) {
          expandedKeys.value = [...expandedKeys.value, key];
        }
      }
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

