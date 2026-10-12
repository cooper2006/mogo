import { defineStore } from 'pinia';
import axios from 'axios';
import { exchangeSsoToken, fetchCurrentProfile, logout as logoutApi } from '@/api/auth';

export interface AdminProfile {
  name: string;
  roleName: string;
  orgName: string;
  username?: string;
  email?: string;
  phone?: string;
  avatarUrl?: string;
  avatarUpdatedAt?: string;
  lastLoginAt?: string;
  tenantId?: string;
}

interface AuthState {
  token: string;
  profile: AdminProfile | null;
  initialized: boolean;
}

const STORAGE_KEY = 'askai-admin-auth';

/** Reserved platform tenant_id; mirrors ``PLATFORM_TENANT_ID`` in admin-api. */
export const PLATFORM_TENANT_ID = '__platform__';

function readState(): AuthState {
  if (typeof window === 'undefined') {
    return { token: '', profile: null, initialized: false };
  }
  const raw = localStorage.getItem(STORAGE_KEY);
  if (!raw) {
    return { token: '', profile: null, initialized: false };
  }
  try {
    const parsed = JSON.parse(raw) as Partial<AuthState>;
    return {
      token: parsed.token || '',
      profile: parsed.profile || null,
      initialized: false,
    };
  } catch {
    return { token: '', profile: null, initialized: false };
  }
}

function persistState(state: Pick<AuthState, 'token' | 'profile'>) {
  if (typeof window === 'undefined') {
    return;
  }
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
}

export const useAuthStore = defineStore('auth', {
  state: (): AuthState => readState(),
  getters: {
    isAuthenticated: (state) => Boolean(state.token),
    isPlatformAdmin: (state) => state.profile?.tenantId === PLATFORM_TENANT_ID,
  },
  actions: {
    clearSession() {
      this.token = '';
      this.profile = null;
      this.initialized = true;
      persistState({ token: '', profile: null });
    },
    login(payload: Pick<AuthState, 'token' | 'profile'>) {
      this.token = payload.token;
      this.profile = payload.profile;
      this.initialized = true;
      persistState({ token: this.token, profile: this.profile });
    },
    setProfile(profile: AdminProfile) {
      this.profile = profile;
      persistState({ token: this.token, profile: this.profile });
    },
    async initializeSession() {
      // 022 FR-14（T031）：SSO 令牌不再从 URL 查询串读取。
      // user-web 用 window.open(url, '_blank', 'state=...') 传入，落在
      // window.history.state 中 —— 不进地址栏、不进浏览器历史、不进访问日志。
      if (typeof window !== 'undefined') {
        const state = window.history.state as { ssoToken?: string } | null;
        const ssoToken = typeof state?.ssoToken === 'string' ? state.ssoToken.trim() : '';
        if (ssoToken) {
          // 立即清掉，保证令牌只被消费一次；即使下方换票失败也不残留。
          window.history.replaceState({}, '');
          try {
            const result = await exchangeSsoToken(ssoToken);
            this.token = result.accessToken;
            this.profile = null;
            this.initialized = false;
            persistState({ token: this.token, profile: null });
          } catch (error) {
            // 换票失败（过期 / 已使用 / 账号停用）→ 回到登录页，不猜测。
            this.clearSession();
            console.warn('[auth] SSO exchange failed:', (error as Error)?.message || error);
          }
        }
      }

      if (this.initialized) {
        return;
      }
      if (!this.token) {
        this.initialized = true;
        return;
      }
      try {
        const profile = await fetchCurrentProfile();
        this.setProfile({
          name: profile.name,
          roleName: profile.roleName,
          orgName: profile.orgName,
          username: profile.username,
          email: profile.email,
          phone: profile.phone,
          avatarUrl: profile.avatarUrl,
          avatarUpdatedAt: profile.avatarUpdatedAt,
          lastLoginAt: profile.lastLoginAt,
          tenantId: profile.tenantId,
        });
      } catch (error) {
        // Only clear local auth on real auth failures.
        // Temporary network issues / 5xx should not force logout.
        if (axios.isAxiosError(error)) {
          const status = error.response?.status;
          if (status === 401 || status === 403) {
            this.clearSession();
          }
        }
      } finally {
        this.initialized = true;
        persistState({ token: this.token, profile: this.profile });
      }
    },
    async logout() {
      if (this.token) {
        try {
          await logoutApi();
        } catch {
          // Ignore remote logout failures and still clear local state.
        }
      }
      this.clearSession();
    },
  },
});
