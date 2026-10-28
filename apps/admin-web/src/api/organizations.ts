import { apiClient } from './client';

export interface AccountGroupItem {
  id: string;
  tenantId: string;
  name: string;
  code: string;
  description: string;
  accountCount: number;
  updatedAt: string;
}

export interface AccountItem {
  id: string;
  tenantId: string;
  username: string;
  displayName: string;
  email: string;
  phone: string;
  groupCode: string;
  groupName: string;
  roleName: string;
  status: 'active' | 'disabled';
  isProtected: boolean;
  updatedAt: string;
}

export interface CreateGroupPayload {
  name: string;
  description: string;
}

export interface UpdateGroupPayload {
  name: string;
  description: string;
}

export interface CreateAccountPayload {
  username: string;
  displayName: string;
  email: string;
  phone: string;
  groupCode: string;
  roleName: string;
  status: 'active' | 'disabled';
  initialPassword: string;
}

export interface UpdateAccountPayload {
  displayName: string;
  email: string;
  phone: string;
  groupCode: string;
  roleName: string;
  status: 'active' | 'disabled';
}

export async function fetchAccountGroups() {
  const { data } = await apiClient.get<AccountGroupItem[]>('/api/v1/organizations/account-groups');
  return data;
}

export async function createAccountGroup(payload: CreateGroupPayload) {
  const { data } = await apiClient.post<AccountGroupItem>('/api/v1/organizations/account-groups', payload);
  return data;
}

export async function updateAccountGroup(id: string, payload: UpdateGroupPayload) {
  const { data } = await apiClient.put<AccountGroupItem>(`/api/v1/organizations/account-groups/${id}`, payload);
  return data;
}

export async function deleteAccountGroup(id: string) {
  const { data } = await apiClient.delete<{ success: boolean }>(`/api/v1/organizations/account-groups/${id}`);
  return data;
}

export async function fetchAccounts() {
  const { data } = await apiClient.get<AccountItem[]>('/api/v1/organizations/accounts');
  return data;
}

export async function createAccount(payload: CreateAccountPayload) {
  const { data } = await apiClient.post<AccountItem>('/api/v1/organizations/accounts', payload);
  return data;
}

export async function updateAccount(id: string, payload: UpdateAccountPayload) {
  const { data } = await apiClient.put<AccountItem>(`/api/v1/organizations/accounts/${id}`, payload);
  return data;
}

export async function deleteAccount(id: string) {
  const { data } = await apiClient.delete<{ success: boolean }>(`/api/v1/organizations/accounts/${id}`);
  return data;
}
