/** 按语言挑选文案：元组顺序固定为 [中文, 英文]。 */
function pickLocale(locale: 'zh' | 'en', texts: [string, string]): string {
  return locale === 'zh' ? texts[0] : texts[1]
}

/** 已知错误特征 → 面向用户的说明；按声明顺序，首个命中的规则生效。 */
const RUNTIME_ERROR_RULES: Array<{ match: (text: string) => boolean; text: [string, string] }> = [
  {
    match: (t) => t.includes('another desktop device'),
    text: [
      '此项目会话绑定在另一台桌面设备。历史记录可查看，但请回到原设备继续执行。',
      'This project task is bound to another desktop device. History remains readable; continue on the original device.',
    ],
  },
  {
    match: (t) => t.includes('workspace') && (t.includes('unavailable') || t.includes('missing')),
    text: [
      '原项目目录已丢失或不可访问。历史记录仍可查看；请恢复原目录后重试。',
      'The original project folder is missing or unavailable. History remains readable; restore the folder and retry.',
    ],
  },
  {
    match: (t) => t.includes('profile') && (t.includes('compatible') || t.includes('changed')),
    text: [
      '当前 DSH Runtime Profile 与该历史会话不兼容。为保护原会话，系统未自动切换执行环境。',
      'The current DSH Runtime Profile is incompatible with this historical task. Execution was not silently moved.',
    ],
  },
  {
    match: (t) => t.includes('runtime') && (t.includes('unavailable') || t.includes('ready')),
    text: [
      '本地 DSH Runtime 当前不可用。历史记录仍可查看，请恢复桌面 Runtime 后重试。',
      'The local DSH Runtime is unavailable. History remains readable; restore the desktop Runtime and retry.',
    ],
  },
]

/** 未命中任何已知特征时的兜底文案。 */
const FALLBACK_MESSAGES: Record<'zh' | 'en', string> = {
  zh: '本地 Code 会话暂时不可用。',
  en: 'The local Code task is unavailable.',
}

export function codeRuntimeErrorMessage(error: unknown, locale: 'zh' | 'en'): string {
  const raw = String(error instanceof Error ? error.message : error || '')
  const rule = RUNTIME_ERROR_RULES.find((r) => r.match(raw.toLowerCase()))
  if (rule) return pickLocale(locale, rule.text)
  return raw || FALLBACK_MESSAGES[locale]
}
