import { apiClient } from './client';
import type { AdminProfile } from '@/stores/auth';

interface LoginPayload {
  username: string;
  password: string;
  tenantId?: string;
}

export interface TenantCandidate {
  tenantId: string;
  orgName: string;
  roleName: string;
  displayName: string;
  username: string;
}

interface LoginResponse {
  token: string;
  profile: AdminProfile;
  requiresTenantSelection?: false;
}

export interface TenantSelectionResponse {
  requiresTenantSelection: true;
  challengeToken: string;
  candidates: TenantCandidate[];
  expiresAt?: string;
}

export async function login(payload: LoginPayload) {
  const { data } = await apiClient.post<LoginResponse | TenantSelectionResponse>('/api/auth/login', payload);
  return data;
}

export async function selectTenantLogin(payload: { challengeToken: string; tenantId: string }) {
  const { data } = await apiClient.post<LoginResponse>('/api/auth/login/select-tenant', payload);
  return data;
}

export interface SsoExchangeResponse {
  accessToken: string;
  expiresAt: number;
  sessionId: string;
}

/**
 * 022 FR-14（T031）：SSO 令牌走 POST 换票，不再出现在 URL 查询串。
 * 令牌由 user-web 通过 ``window.open(..., state)`` 传入，落在
 * ``window.history.state`` 里，绝不出现在地址栏 / 访问日志 / 书签中。
 */
export async function exchangeSsoToken(ssoToken: string) {
  const { data } = await apiClient.post<{
    code: number;
    message?: string;
    data: SsoExchangeResponse;
  }>('/api/auth/sso/exchange', { sso_token: ssoToken });
  if (data.code !== 0 || !data.data?.accessToken) {
    throw new Error(data.message || 'SSO 换票失败');
  }
  return data.data;
}

export async function fetchCurrentProfile() {
  const { data } = await apiClient.get<AdminProfile & { username: string }>('/api/auth/me');
  return data;
}

export async function updateCurrentProfile(payload: { name: string; email: string; phone: string }) {
  const { data } = await apiClient.patch<AdminProfile & { username: string }>('/api/auth/me', payload);
  return data;
}

export async function changeCurrentPassword(payload: { currentPassword: string; newPassword: string }) {
  const { data } = await apiClient.post<{ success: boolean }>('/api/auth/me/password', payload);
  return data;
}

export async function uploadCurrentAvatar(file: File) {
  const formData = new FormData();
  formData.append('file', file);
  const { data } = await apiClient.post<AdminProfile & { username: string }>('/api/auth/me/avatar', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return data;
}

export async function logout() {
  const { data } = await apiClient.post<{ success: boolean }>('/api/auth/logout');
  return data;
}
