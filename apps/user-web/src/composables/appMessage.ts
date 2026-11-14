// apps/user-web/src/composables/appMessage.ts
// App.vue 自身是 <n-message-provider> 的宿主（provider 在它自己的模板里），
// 因此 App.vue 的 setup 顶层不能调用 useMessage()——naive-ui 用 inject 向上找，
// 找不到祖先 provider 会直接抛 "No outer <n-message-provider /> founded"。
//
// 这里用模块级 shallowRef 承载 message API：由 App.vue 模板中位于 provider
// 内部的 <AppMessageBridge> 组件在挂载时注册，App.vue 的事件回调再按需取用。
// 桥接组件位于 n-config-provider 之内，因此消息渲染能正确继承主题。

import { shallowRef, type ShallowRef } from 'vue'
import { type MessageApi } from 'naive-ui'

const messageApi: ShallowRef<MessageApi | null> = shallowRef(null)

export function registerAppMessage(api: MessageApi): void {
  messageApi.value = api
}

export function useAppMessage(): MessageApi | null {
  return messageApi.value
}
