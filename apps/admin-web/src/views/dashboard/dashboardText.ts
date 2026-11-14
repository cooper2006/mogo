import { t } from '@/composables/i18n';

/** Translate dashboard messages that are returned as legacy human-readable text. */
export function translateDashboardText(value: string | null | undefined): string {
  const text = String(value || '');
  if (!text) return '';

  let match = text.match(/^(\d+) 个工具连接需要检查。$/);
  if (match) return t('工具连接需要检查', { count: match[1] });

  match = text.match(/^(\d+) 个工具尚未测试连通性。$/);
  if (match) return t('工具尚未测试连通性', { count: match[1] });

  match = text.match(/^(\d+) 个模型最近测试失败。$/);
  if (match) return t('模型最近测试失败', { count: match[1] });

  match = text.match(/^(\d+) 次调用失败，建议查看 Token 统计。$/);
  if (match) return t('调用失败建议查看 Token 统计', { count: match[1] });

  match = text.match(/^(\d+) 个 Skill 最近调用最多。$/);
  if (match) return t('Skill 最近调用最多', { count: match[1] });

  match = text.match(/^(\d+) 种检索类型最近使用最多。$/);
  if (match) return t('检索类型最近使用最多', { count: match[1] });

  return t(text);
}
