import type { LabelMap } from '../messages';

/** Model-group (shared connection) + model-pricing labels merged in for 5.4. */
export const modelGroupMessages: Record<string, LabelMap> = {
  // === 通用操作（组件内直接 t('add') 等，本地字典补齐中文） ===
  'add': { 'zh-CN': '添加', 'en-US': 'Add' },
  'cancel': { 'zh-CN': '取消', 'en-US': 'Cancel' },
  'deleted': { 'zh-CN': '已删除', 'en-US': 'Deleted' },
  'edit': { 'zh-CN': '编辑', 'en-US': 'Edit' },
  'saved': { 'zh-CN': '已保存', 'en-US': 'Saved' },
  'select': { 'zh-CN': '选择', 'en-US': 'Select' },
  'tested': { 'zh-CN': '已测试', 'en-US': 'Tested' },
  // === legacy.*（himovo messages.ts 有定义，本地补齐） ===
  'legacy.cancel': { 'zh-CN': '取消', 'en-US': 'Cancel' },
  'legacy.capabilities': { 'zh-CN': '能力', 'en-US': 'Capabilities' },
  'legacy.connecting_to_model': { 'zh-CN': '正在连接模型...', 'en-US': 'Connecting to model...' },
  'legacy.delete_model': { 'zh-CN': '删除模型', 'en-US': 'Delete Model' },
  'legacy.display_name': { 'zh-CN': '显示名称', 'en-US': 'Display Name' },
  'legacy.enter_a_valid_json_object': { 'zh-CN': '请输入有效的 JSON 对象', 'en-US': 'Enter a valid JSON object' },
  'legacy.model_connection_tested_successfully': { 'zh-CN': '模型连接测试成功。', 'en-US': 'Model connection tested successfully.' },
  'legacy.model_id': { 'zh-CN': '模型 ID', 'en-US': 'Model ID' },
  'legacy.reply_in_one_sentence_to_test_the_current_model': { 'zh-CN': '请用一句话回复当前模型连接测试。', 'en-US': 'Reply in one sentence to test the current model connection.' },
  'legacy.request_failed': { 'zh-CN': '请求失败', 'en-US': 'Request failed' },
  'legacy.status': { 'zh-CN': '状态', 'en-US': 'Status' },
  'legacy.test_failed': { 'zh-CN': '测试失败', 'en-US': 'Test failed' },
  'legacy.the_embedding_endpoint_will_be_called_and_its_vector': { 'zh-CN': '将调用 Embedding 接口并校验返回向量。', 'en-US': 'The Embedding endpoint will be called and its vector response validated.' },
  'legacy.the_rerank_endpoint_will_be_called_and_its_ranking': { 'zh-CN': '将调用 Rerank 接口并校验排序结果。', 'en-US': 'The Rerank endpoint will be called and its ranking response validated.' },
  // === modelPricing.*（himovo messages.ts 有定义） ===
  'modelPricing.enable': { 'zh-CN': '配置模型单价', 'en-US': 'Configure model pricing' },
  'modelPricing.help': { 'zh-CN': '按每 100 万 Token 的输入和输出单价估算成本；未配置的调用不会计入成本。', 'en-US': 'Estimate costs from input and output rates per million tokens. Unpriced calls are excluded.' },
  'modelPricing.currency': { 'zh-CN': '币种', 'en-US': 'Currency' },
  'modelPricing.input': { 'zh-CN': '输入单价 / 100 万 Token', 'en-US': 'Input per million tokens' },
  'modelPricing.output': { 'zh-CN': '输出单价 / 100 万 Token', 'en-US': 'Output per million tokens' },
  // === additional.image_*（himovo additionalMessages.ts 有定义） ===
  'additional.image_generation_test_succeeded': { 'zh-CN': '图片生成测试成功。', 'en-US': 'Image generation test succeeded.' },
  'additional.image_generation_test_failed': { 'zh-CN': '图片生成测试失败。', 'en-US': 'Image generation test failed.' },
  'additional.image_model_test_result': { 'zh-CN': '图片模型测试结果', 'en-US': 'Image model test result' },
};
