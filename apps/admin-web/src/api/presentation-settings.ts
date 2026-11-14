import { apiClient } from './client';


export interface PresentationSettings {
  configured: boolean;
  enabled: boolean;
  available: boolean;
  llmModelId: string;
  imageModelId: string;
  updatedAt: string;
}

export interface PresentationSettingsPayload {
  enabled: boolean;
  llmModelId: string;
  imageModelId: string;
}

export async function fetchPresentationSettings() {
  const { data } = await apiClient.get<PresentationSettings>('/api/v1/settings/presentation');
  return data;
}

export async function savePresentationSettings(payload: PresentationSettingsPayload) {
  const { data } = await apiClient.put<PresentationSettings>('/api/v1/settings/presentation', payload);
  return data;
}
