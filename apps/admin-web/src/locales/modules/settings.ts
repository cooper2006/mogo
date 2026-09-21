import type { LabelMap } from '../messages';

/** Settings-page labels shared by external search, page collection, and knowledge parsing. */
export const settingsMessages: Record<string, LabelMap> = {
  '页面采集': { 'zh-CN': '页面采集', 'en-US': 'Page Collection' },
  '文档解析': { 'zh-CN': '文档解析', 'en-US': 'Document Parsing' },
  '配置 web_search 默认调用的外部搜索源。': { 'zh-CN': '配置 web_search 默认调用的外部搜索源。', 'en-US': 'Configure the external search provider used by web_search by default.' },
  '未保存 API Key': { 'zh-CN': '未保存 API Key', 'en-US': 'API Key not saved' },
  '当前默认': { 'zh-CN': '当前默认', 'en-US': 'Current default' },
  '设为默认': { 'zh-CN': '设为默认', 'en-US': 'Set as default' },
  '留空则保留已保存 Key': { 'zh-CN': '留空则保留已保存 Key', 'en-US': 'Leave blank to keep the saved key' },
  '填写 API Key': { 'zh-CN': '填写 API Key', 'en-US': 'Enter API Key' },
  '测试连接': { 'zh-CN': '测试连接', 'en-US': 'Test Connection' },
  '连接测试通过': { 'zh-CN': '连接测试通过', 'en-US': 'Connection test passed' },
  '连接测试失败': { 'zh-CN': '连接测试失败', 'en-US': 'Connection test failed' },
  '配置网页正文采集能力，用于从 URL 提取页面内容。': { 'zh-CN': '配置网页正文采集能力，用于从 URL 提取页面内容。', 'en-US': 'Configure page content extraction from URLs.' },
  '默认搜索源已更新': { 'zh-CN': '默认搜索源已更新', 'en-US': 'Default search provider updated' },
  '连接成功': { 'zh-CN': '连接成功', 'en-US': 'Connection successful' },
  '测试完成，但未返回可展示结果': { 'zh-CN': '测试完成，但未返回可展示结果', 'en-US': 'Test completed, but returned no displayable result' },
};
