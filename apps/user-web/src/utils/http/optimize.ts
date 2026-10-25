// apps/user-web/src/utils/http/optimize.ts
// 026 T038 — API 请求优化工具（FR-25）
//
// 四类原语：debounce（输入防抖）/ throttle（滚动节流）/ createRequestDeduper
// （同资源请求合并去重）/ createPagedLoader（分页加载封装）。
// 目标：首屏请求数 ≤ 10（FR-25 预算）。

export interface Debounced<T extends (...args: never[]) => void> {
  (...args: Parameters<T>): void
  cancel(): void
}

export function debounce<T extends (...args: never[]) => void>(fn: T, waitMs = 300): Debounced<T> {
  let timer: ReturnType<typeof setTimeout> | null = null
  const wrapped: Debounced<T> = (...args: Parameters<T>) => {
    if (timer) clearTimeout(timer)
    timer = setTimeout(() => {
      timer = null
      fn(...args)
    }, waitMs)
  }
  wrapped.cancel = () => {
    if (timer) clearTimeout(timer)
    timer = null
  }
  return wrapped
}

export function throttle<T extends (...args: never[]) => void>(fn: T, intervalMs = 200): (...args: Parameters<T>) => void {
  let last = 0
  let trailing: ReturnType<typeof setTimeout> | null = null
  let lastArgs: Parameters<T> | null = null

  const invoke = (args: Parameters<T>) => {
    last = Date.now()
    trailing = null
    fn(...args)
  }

  return (...args: Parameters<T>) => {
    const now = Date.now()
    const remain = intervalMs - (now - last)
    if (remain <= 0) {
      if (trailing) {
        clearTimeout(trailing)
        trailing = null
      }
      invoke(args)
      return
    }
    lastArgs = args
    if (!trailing) {
      trailing = setTimeout(() => {
        if (lastArgs) invoke(lastArgs)
      }, remain)
    }
  }
}

/** 同资源请求合并：相同 key 的并发调用共享同一个 Promise */
export function createRequestDeduper() {
  const inflight = new Map<string, Promise<unknown>>()

  function dedupe<T>(key: string, fn: () => Promise<T>): Promise<T> {
    const existing = inflight.get(key)
    if (existing) return existing as Promise<T>
    const p = fn()
      .catch((err) => {
        inflight.delete(key)
        throw err
      })
      .finally(() => {
        inflight.delete(key)
      })
    inflight.set(key, p)
    return p
  }

  function pendingCount(): number {
    return inflight.size
  }

  return { dedupe, pendingCount }
}

export interface PagedResult<T> {
  items: T[]
  total: number
}

/** 分页加载封装：自动 offset/limit、page 去重、追加模式 */
export function createPagedLoader<T>(options: {
  fetchPage: (offset: number, limit: number) => Promise<PagedResult<T>>
  limit?: number
}) {
  const limit = options.limit ?? 20
  const deduper = createRequestDeduper()
  const items: T[] = []
  let total = 0
  let loading = false

  async function load(reset = false): Promise<T[]> {
    if (loading) return items
    if (reset) items.length = 0
    const offset = items.length
    if (!reset && offset >= total && total > 0) return items
    loading = true
    try {
      const page = await deduper.dedupe(`${offset}:${limit}`, () => options.fetchPage(offset, limit))
      total = page.total
      items.push(...page.items)
      return items
    } finally {
      loading = false
    }
  }

  return {
    items,
    get total() {
      return total
    },
    get hasMore() {
      return total === 0 ? false : items.length < total
    },
    load,
  }
}