import { translateSourceText, useLocale } from '@/composables/i18n';

export function localizedServerText(value: unknown, fallback: string): string {
  if (typeof value !== 'string' || !value) return fallback;
  const translated = translateSourceText(value);
  if (useLocale().locale.value === 'en-US' && /[\u3400-\u9fff]/u.test(translated)) return fallback;
  return translated;
}
