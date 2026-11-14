// apps/user-web/src/composables/virtual.ts
// 026 T039 — 虚拟列表 composable（FR-26）
//
// 大数据集（> 1000 项）仅渲染可视区。原生 IntersectionObserver 实现（零依赖）；
// 需要动态行高 / 窗口化时可安装 vue-virtual-scroller 后替换。
//
// 用法：
//   const v = useVirtualList({ itemCount: 10000, itemHeight: 48, overscan: 6 })
//   <div ref="v.containerRef" style="overflow:auto" @scroll="v.onScroll">
//     <div :style="{ height: v.totalHeight.value + 'px', position: 'relative' }">
//       <div v-for="i in v.list.value" :key="i" :style="{ position: 'absolute', top: (v.startIndex.value + i) * 48 + 'px', height: '48px' }">{{ i }}</div>
//       <div ref="v.sentinelRef" />
//     </div>
//   </div>

import { computed, onBeforeUnmount, ref, type Ref } from 'vue'

export interface UseVirtualListOptions {
  itemCount: number
  itemHeight: number
  overscan?: number
  loadMore?: () => void | Promise<void>
}

export interface UseVirtualListReturn {
  list: Ref<number[]>
  startIndex: Ref<number>
  totalHeight: Ref<number>
  containerRef: Ref<HTMLElement | null>
  sentinelRef: Ref<HTMLElement | null>
  onScroll: (evt: Event) => void
}

export function useVirtualList(options: UseVirtualListOptions): UseVirtualListReturn {
  const { itemCount, itemHeight, overscan = 6, loadMore } = options
  const containerRef = ref<HTMLElement | null>(null)
  const sentinelRef = ref<HTMLElement | null>(null)
  const startIndex = ref(0)
  const endIndex = ref(Math.min(itemCount, 1))
  const totalHeight = computed(() => itemCount * itemHeight)
  let viewportHeight = 600
  let loadingMore = false
  let io: IntersectionObserver | null = null

  function recalc() {
    const el = containerRef.value
    if (el) viewportHeight = el.clientHeight || viewportHeight
    const visible = Math.ceil(viewportHeight / itemHeight) + overscan * 2
    const start = Math.max(0, startIndex.value - overscan)
    const end = Math.min(itemCount, startIndex.value + visible + overscan)
    startIndex.value = start
    endIndex.value = end
  }

  const list = computed<number[]>(() => {
    const out: number[] = []
    for (let i = startIndex.value; i < endIndex.value && i < itemCount; i++) out.push(i)
    return out
  })

  function onScroll(evt: Event) {
    const target = evt.currentTarget as HTMLElement
    const index = Math.floor(target.scrollTop / itemHeight)
    if (index !== startIndex.value) {
      startIndex.value = index
      recalc()
    }
  }

  if (typeof IntersectionObserver !== 'undefined') {
    io = new IntersectionObserver(
      (entries) => {
        if (!entries[0]?.isIntersecting || loadingMore || !loadMore) return
        loadingMore = true
        void Promise.resolve(loadMore()).finally(() => {
          loadingMore = false
        })
      },
      { rootMargin: '0px 0px 200px 0px' },
    )
  }

  let observeTimer: ReturnType<typeof setTimeout> | null = null
  const waitObserver = () => {
    if (containerRef.value && sentinelRef.value) {
      if (io && sentinelRef.value) io.observe(sentinelRef.value)
      recalc()
    } else {
      observeTimer = setTimeout(waitObserver, 30)
    }
  }
  observeTimer = setTimeout(waitObserver, 0)

  onBeforeUnmount(() => {
    if (observeTimer) clearTimeout(observeTimer)
    io?.disconnect()
  })

  return { list, startIndex, totalHeight, containerRef, sentinelRef, onScroll }
}

export default useVirtualList