import { createRouter, createWebHistory, type RouteLocationNormalized } from 'vue-router';
import { appRoutes } from './routes';
import { useAuthStore } from '@/stores/auth';
import { useSetupStore } from '@/stores/setup';

export const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: appRoutes,
});

type SetupStore = ReturnType<typeof useSetupStore>;
type AuthStore = ReturnType<typeof useAuthStore>;

/**
 * 平台初始化未完成时的重定向决议：需要跳转则返回目标路径，返回 null 表示放行。
 * 邀请链接落地页跳过初始化校验，避免接收邀请被重定向到 /setup。
 */
async function resolveSetupRedirect(to: RouteLocationNormalized, setupStore: SetupStore): Promise<string | null> {
  if (to.path === '/invite/accept') return null;
  try {
    await setupStore.ensureStatus();
    return !setupStore.completed && to.path !== '/setup' ? '/setup' : null;
  } catch {
    return to.path !== '/setup' ? '/setup' : null;
  }
}

/** 登录态与身份下的路由决议：返回 true 放行，或返回需要重定向的路径。 */
function resolveAuthRedirect(to: RouteLocationNormalized, authStore: AuthStore): boolean | string {
  if (to.meta.public) return true;
  const isPlatformAdmin = authStore.isPlatformAdmin;
  if (to.path === '/login') {
    return authStore.isAuthenticated ? (isPlatformAdmin ? '/platform/tenants' : '/dashboard') : true;
  }
  if (!authStore.isAuthenticated) return to.meta.platformOnly ? '/platform/login' : '/login';
  // Platform console pages are only reachable with a ``__platform__`` identity.
  if (to.meta.platformOnly && !isPlatformAdmin) return '/dashboard';
  // The platform admin only gets the platform console: tenant business routes are rejected
  // for the reserved identifier. ``/profile`` stays reachable for account self-service.
  if (isPlatformAdmin && !to.meta.platformOnly && !to.path.startsWith('/profile')) {
    return '/platform/tenants';
  }
  return true;
}

router.beforeEach(async (to) => {
  const setupStore = useSetupStore();
  const setupRedirect = await resolveSetupRedirect(to, setupStore);
  if (setupRedirect) return setupRedirect;
  const authStore = useAuthStore();
  await authStore.initializeSession();
  return resolveAuthRedirect(to, authStore);
});
