import { createRouter, createWebHistory } from 'vue-router';
import { appRoutes } from './routes';
import { useAuthStore } from '@/stores/auth';
import { useSetupStore } from '@/stores/setup';

export const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: appRoutes,
});

router.beforeEach(async (to) => {
  const setupStore = useSetupStore();
  if (to.path !== '/invite/accept') {
    try {
      await setupStore.ensureStatus();
      if (!setupStore.completed && to.path !== '/setup') {
        return '/setup';
      }
      // When the platform admin already exists, /setup degrades to a shortcut
      // entry (decision 12) instead of redirecting away.
    } catch {
      if (to.path !== '/setup') return '/setup';
    }
  }
  const authStore = useAuthStore();
  if (to.meta.public) {
    return true;
  }
  await authStore.initializeSession();
  const isPlatformAdmin = authStore.isPlatformAdmin;
  if (to.path === '/login') {
    if (authStore.isAuthenticated) {
      return isPlatformAdmin ? '/platform/tenants' : '/dashboard';
    }
    return true;
  }
  if (!authStore.isAuthenticated) {
    return to.meta.platformOnly ? '/platform/login' : '/login';
  }
  // Platform console pages are only reachable with a ``__platform__`` identity.
  if (to.meta.platformOnly && !isPlatformAdmin) {
    return '/dashboard';
  }
  // The platform admin only gets the platform console: tenant business routes are rejected
  // for the reserved identifier. ``/profile`` stays reachable for account self-service.
  if (isPlatformAdmin && !to.meta.platformOnly && !to.path.startsWith('/profile')) {
    return '/platform/tenants';
  }
  return true;
});
