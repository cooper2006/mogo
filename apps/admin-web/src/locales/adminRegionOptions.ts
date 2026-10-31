type AdminLanguage = 'zh-CN' | 'en-US';

export const adminLanguageNames: Record<AdminLanguage, string> = {
  'zh-CN': '简体中文',
  'en-US': 'English',
};

export const adminLanguageChangedMessages: Record<AdminLanguage, string> = {
  'zh-CN': '语言已切换为简体中文',
  'en-US': 'Language switched to English',
};

const timezones = [
  { value: 'Asia/Shanghai', zh: '中国标准时间 (GMT+8) - Asia/Shanghai', en: 'China Standard Time (GMT+8) - Asia/Shanghai' },
  { value: 'Asia/Tokyo', zh: '日本标准时间 (GMT+9) - Asia/Tokyo', en: 'Japan Standard Time (GMT+9) - Asia/Tokyo' },
  { value: 'UTC', zh: '协调世界时 (UTC) - UTC', en: 'Coordinated Universal Time (UTC) - UTC' },
  { value: 'Europe/Berlin', zh: '欧洲中部时间 (GMT+1) - Europe/Berlin', en: 'Central European Time (GMT+1) - Europe/Berlin' },
  { value: 'Europe/London', zh: '格林威治标准时间 (GMT) - Europe/London', en: 'Greenwich Mean Time (GMT) - Europe/London' },
  { value: 'America/New_York', zh: '美国东部标准时间 (GMT-5) - America/New_York', en: 'Eastern Standard Time (GMT-5) - America/New_York' },
  { value: 'America/Chicago', zh: '美国中部标准时间 (GMT-6) - America/Chicago', en: 'Central Standard Time (GMT-6) - America/Chicago' },
  { value: 'America/Los_Angeles', zh: '太平洋标准时间 (GMT-8) - America/Los_Angeles', en: 'Pacific Standard Time (GMT-8) - America/Los_Angeles' },
  { value: 'Australia/Sydney', zh: '澳大利亚东部标准时间 (GMT+10) - Australia/Sydney', en: 'Australian Eastern Standard Time (GMT+10) - Australia/Sydney' },
] as const;

export function adminTimezoneOptions(locale: AdminLanguage) {
  const language = locale === 'en-US' ? 'en' : 'zh';
  return timezones.map(({ value, ...labels }) => ({ value, label: labels[language] }));
}
