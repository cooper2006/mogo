import { t } from '@/composables/i18n'

type ProviderLike = {
  code?: string
  name?: string
  providerType?: string
}

const providerMessageKeys: Record<string, string> = {
  openai: 'OpenAI',
  azure_openai: 'Azure OpenAI',
  qwen: '通义千问',
  tongyi: '通义千问',
  dashscope: '通义千问',
  aliyun: '通义千问',
  deepseek: 'DeepSeek',
  custom: '自定义兼容接口',
  custom_compatible: '自定义兼容接口',
  custom_openai: '自定义兼容接口',
}

export function providerLabel(provider?: Partial<ProviderLike> | null): string {
  if (!provider) return t('未选择')
  const code = String(provider.code || '').toLowerCase()
  const name = String(provider.name || '').toLowerCase()
  const key = providerMessageKeys[code]
  if (key) return t(key)
  if (name.includes('qwen') || name.includes('通义') || name.includes('dashscope')) return t('通义千问')
  if (name.includes('deepseek')) return t('DeepSeek')
  if (name.includes('azure')) return t('Azure OpenAI')
  if (name.includes('custom') || name.includes('自定义')) return t('自定义兼容接口')
  if (provider.providerType === 'azure_openai') return t('Azure OpenAI')
  return provider.name || t('自定义')
}
