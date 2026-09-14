import { t } from '../../composables/i18n'

export function skillActionErrorMessage(error: any, fallbackKey: string): string {
  const detail = error?.response?.data?.detail
  const code = typeof detail === 'object' ? String(detail?.code || '') : ''
  if (code) {
    const key = `skills.error.${code}`
    const translated = t(key)
    if (translated !== key) return translated
  }
  if (typeof detail === 'string' && detail.trim()) return detail
  if (!code && typeof detail?.message === 'string' && detail.message.trim()) return detail.message
  return t(fallbackKey)
}
