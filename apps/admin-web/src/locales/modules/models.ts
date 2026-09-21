import type { LabelMap } from '../messages';

/** Model-center labels kept separate from page components so locale changes stay consistent. */
export const modelMessages: Record<string, LabelMap> = {
  'model.capability.chat': { 'zh-CN': '对话', 'en-US': 'Chat' },
  'model.capability.vision': { 'zh-CN': '视觉', 'en-US': 'Vision' },
  'model.capability.embedding': { 'zh-CN': '向量', 'en-US': 'Embedding' },
  'model.capability.rerank': { 'zh-CN': '重排', 'en-US': 'Rerank' },
  'model.capability.image_generation': { 'zh-CN': '图片生成', 'en-US': 'Image Generation' },
};
