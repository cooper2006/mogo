import axios from 'axios';
import { useAuthStore } from '@/stores/auth';

export const apiClient = axios.create({
  baseURL: import.meta.env.VITE_ADMIN_API_BASE_URL || '/admin-api',
  timeout: 10000,
});

/**
 * Login page inside the admin app, honoring the Vite base (e.g. ``/admin``).
 * A bare ``/login`` would hit the user portal instead of the admin console.
 */
function adminLoginPath(isPlatformAdmin: boolean) {
  const base = import.meta.env.BASE_URL.replace(/\/$/, '');
  return isPlatformAdmin ? `${base}/platform/login` : `${base}/login`;
}

/** Bounce to the login page matching the current identity; no-op when already there. */
export function redirectToLogin(isPlatformAdmin = false) {
  if (typeof window === 'undefined') {
    return;
  }
  const base = import.meta.env.BASE_URL.replace(/\/$/, '');
  const current = window.location.pathname.replace(/\/+$/, '') || '/';
  if (current === `${base}/login` || current === `${base}/platform/login`) {
    return;
  }
  // An expired session loses its profile, so fall back to the area the user is browsing.
  const usePlatformLogin = isPlatformAdmin || current.startsWith(`${base}/platform`);
  window.location.replace(adminLoginPath(usePlatformLogin));
}

apiClient.interceptors.request.use((config) => {
  const authStore = useAuthStore();
  if (authStore.token) {
    config.headers.Authorization = `Bearer ${authStore.token}`;
  }
  return config;
});

apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (axios.isAxiosError(error)) {
      const status = error.response?.status;
      if (status === 401 || status === 403) {
        const authStore = useAuthStore();
        const isPlatformAdmin = authStore.isPlatformAdmin;
        if (authStore.token) {
          authStore.clearSession();
        }
        redirectToLogin(isPlatformAdmin);
      }
    }
    return Promise.reject(error);
  },
);
