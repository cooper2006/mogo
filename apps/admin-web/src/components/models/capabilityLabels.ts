import { t } from '@/composables/i18n';

const capabilityMessageKeys: Record<string, string> = {
  chat: 'model.capability.chat',
  vision: 'model.capability.vision',
  embedding: 'model.capability.embedding',
  rerank: 'model.capability.rerank',
  image_generation: 'model.capability.image_generation',
};

export function capabilityLabel(value: string): string {
  return t(capabilityMessageKeys[value] || value);
}
