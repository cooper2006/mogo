/**
 * 026 T039 — 虚拟列表 composable（FR-26）
 *
 * 大数据集（> 1000 项）仅渲染可视区。原生实现（IntersectionObserver 观测底部锚点），
 * 不引入第三方依赖；如需 `vue-virtual-scroller` 的窗口化/动态行高，可安装后替换。
 *
 * 用法：
 *   const { list, startIndex, totalHeight, onScroll, containerRef, sentinelRef } =
 *     useVirtualList({ itemCount: 10000, itemHeight: 48, overscan: 6 })
 *
 * 模板示意：
 *   <div ref="containerRef" style="overflow:auto" @scroll="onScroll">
 *     <div :style="{ height: totalHeight + 'px', position: 'relative' }">
 *       <div v-for="i in list" :key="i" :style="{ position: 'absolute', top: (startIndex + list.indexOf(i)) * itemHeight + 'px', height: itemHeight + 'px' }">
 *         {{ i }}
 *       </div>
 *       <div ref="sentinelRef" style="position:absolute; bottom:0" />
 *     </div>
 *   </div>
 *
 * 说明：`loadMore` 在 sentinel 进入可视区时触发一次（节流），用于增量加载。
 */

import { computed, onBeforeUnmount, ref, type Ref } from 'vue';

export interface UseVirtualListOptions {
  /** 总条目数 */
  itemCount: number;
  /** 行高（px，等高等距场景） */
  itemHeight: number;
  /** 可视区外预渲染行数 */
  overscan?: number;
  /** 触发加载更多（sentinel 可见时回调一次） */
  loadMore?: () => void | Promise<void>;
}

export interface UseVirtualListReturn {
  /** 当前需要渲染的条目下标数组 */
  list: Ref<number[]>;
  /** 首个可见条目下标 */
  startIndex: Ref<number>;
  /** 内容总高度 */
  totalHeight: Ref<number>;
  /** 滚动容器引用 */
  containerRef: Ref<HTMLElement | null>;
  /** 底部哨兵（用于 loadMore） */
  sentinelRef: Ref<HTMLElement | null>;
  /** 绑定到滚动容器的滚动处理器 */
  onScroll: (evt: Event) => void;
}

export function useVirtualList(options: UseVirtualListOptions): UseVirtualListReturn {
  const { itemCount, itemHeight, overscan = 6, loadMore } = options;
  const containerRef = ref<HTMLElement | null>(null);
  const sentinelRef = ref<HTMLElement | null>(null);
  const startIndex = ref(0);
  const endIndex = ref(Math.min(itemCount, 1));
  const totalHeight = computed(() => itemCount * itemHeight);
  let viewportHeight = 600;
  let loadingMore = false;
  let io: IntersectionObserver | null = null;

  function recalc() {
    const el = containerRef.value;
    if (el) viewportHeight = el.clientHeight || viewportHeight;
    const visible = Math.ceil(viewportHeight / itemHeight) + overscan * 2;
    const start = Math.max(0, startIndex.value - overscan);
    const end = Math.min(itemCount, startIndex.value + visible + overscan);
    startIndex.value = start;
    endIndex.value = end;
  }

  const list = computed<number[]>(() => {
    const out: number[] = [];
    for (let i = startIndex.value; i < endIndex.value && i < itemCount; i++) out.push(i);
    return out;
  });

  function onScroll(evt: Event) {
    const target = evt.currentTarget as HTMLElement;
    const index = Math.floor(target.scrollTop / itemHeight);
    if (index !== startIndex.value) {
      startIndex.value = index;
      recalc();
    }
  }

  // 观测哨兵：进入可视区触发 loadMore（同页内节流）
  if (typeof IntersectionObserver !== 'undefined') {
    io = new IntersectionObserver(
      (entries) => {
        if (!entries[0]?.isIntersecting || loadingMore || !loadMore) return;
        loadingMore = true;
        void Promise.resolve(loadMore()).finally(() => {
          loadingMore = false;
        });
      },
      { rootMargin: '0px 0px 200px 0px' },
    );
  }

  // 挂载后观测哨兵 + 计算初始范围
  let observeTimer: ReturnType<typeof setTimeout> | null = null;
  const waitObserver = () => {
    if (containerRef.value && sentinelRef.value) {
      if (io && sentinelRef.value) io.observe(sentinelRef.value);
      recalc();
    } else {
      observeTimer = setTimeout(waitObserver, 30);
    }
  };
  observeTimer = setTimeout(waitObserver, 0);

  onBeforeUnmount(() => {
    if (observeTimer) clearTimeout(observeTimer);
    io?.disconnect();
  });

  return { list, startIndex, totalHeight, containerRef, sentinelRef, onScroll };
}

export default useVirtualList