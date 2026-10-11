// apps/user-web/src/composables/useNetworkStatus.ts
// 全局网络状态监听（QF-322）
//
// 监听 navigator.onLine + online/offline 事件，
// 提供响应式的在线/离线状态，供离线横幅等 UI 使用。

import { computed, onBeforeUnmount, onMounted, ref } from 'vue';

let _online: ReturnType<typeof ref<boolean>> | null = null;
let _initialized = false;

function ensureSingleton() {
  if (!_initialized) {
    _online = ref<boolean>(navigator.onLine);
    _initialized = true;
  }
  return _online!;
}

export function useNetworkStatus() {
  const online = ensureSingleton();
  const offline = computed(() => !online.value);

  onMounted(() => {
    const onOnline = () => { online.value = true; };
    const onOffline = () => { online.value = false; };
    window.addEventListener('online', onOnline);
    window.addEventListener('offline', onOffline);

    // 存储解绑函数供 onBeforeUnmount 使用
    (online as any)._cleanup = () => {
      window.removeEventListener('online', onOnline);
      window.removeEventListener('offline', onOffline);
    };
  });

  onBeforeUnmount(() => {
    (online as any)._cleanup?.();
  });

  return { online, offline };
}
