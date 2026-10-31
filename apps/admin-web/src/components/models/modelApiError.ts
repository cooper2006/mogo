import axios from 'axios';
import { t } from '@/composables/i18n';
import { localizedServerText } from '@/utils/serverText';

interface FieldError {
  loc?: Array<string | number>;
  msg?: string;
}

export function modelApiErrorText(error: unknown): string {
  if (!axios.isAxiosError(error)) return localizedServerText(String(error), t('legacy.request_failed'));
  const detail: unknown = error.response?.data?.detail;
  if (typeof detail === 'string' && detail) return localizedServerText(detail, t('legacy.request_failed'));
  if (Array.isArray(detail)) {
    const messages = detail.map((item: FieldError) => {
      const field = Array.isArray(item?.loc) ? item.loc.filter((part) => part !== 'body').join('.') : '';
      return [field, item?.msg].filter(Boolean).join(': ');
    }).filter(Boolean);
    if (messages.length) return localizedServerText(messages.join('; '), t('legacy.request_failed'));
  }
  if (detail && typeof detail === 'object') {
    const message = (detail as { message?: unknown }).message;
    if (typeof message === 'string' && message) return localizedServerText(message, t('legacy.request_failed'));
  }
  return localizedServerText(error.message, t('legacy.request_failed'));
}
