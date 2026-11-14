/**
 * 026 T033 — Web Vitals 采集（FR-21）
 *
 * 采集 LCP / FID / INP / CLS / TTFB 并上报后端。
 * 使用原生 PerformanceObserver 实现（零依赖，不阻塞构建）；
 * 生产建议在 package.json 安装 `web-vitals` 后，将 `nativeCollect()` 替换为
 * `import { onLCP, onFID, onINP, onCLS, onTTFB } from 'web-vitals'` 三行等价调用，
 * 上报管道（sendBeacon / 端点）无需改动。
 *
 * 用法（main.ts 或 bootstrap）：
 *   import { initVitals } from '@/plugins/vitals'
 *   initVitals({ reportUrl: '/api/v1/metrics/vitals' })
 *
 * 上报走 `navigator.sendBeacon`（页面卸载时仍会送达），端点可由
 * `VITE_VITALS_REPORT_URL` 覆盖；未配置时只采集不上报（避免 404 噪音）。
 */

export interface VitalsReport {
  /** 最大内容绘制 ms（LCP） */
  lcp?: number
  /** 首次输入延迟 ms（FID） */
  fid?: number
  /** 输入到下一帧交互 ms（INP，Chrome 96+） */
  inp?: number
  /** 累积布局偏移（CLS，无单位） */
  cls?: number
  /** 首个字节耗时 ms（TTFB） */
  ttfb?: number
  /** 当前页面路径 */
  url: string
  /** 上报时间 ISO */
  sentAt: string
  /** navigator.connection 有效类型（4g/3g…） */
  effectiveType?: string
}

export interface VitalsOptions {
  /** 上报端点；空字符串 = 只采集不上报 */
  reportUrl?: string
  /** 是否用 sendBeacon（默认 true） */
  useBeacon?: boolean
}

const REPORT_URL =
  (import.meta.env.VITE_VITALS_REPORT_URL as string | undefined) || ''

/** 原生 PerformanceObserver 兜底采集 */
function nativeCollect(onReport: (r: Partial<VitalsReport>) => void): void {
  try {
    new PerformanceObserver((list) => {
      const entries = list.getEntries()
      const last = entries[entries.length - 1] as PerformanceEntry & {
        startTime: number
      }
      if (last) onReport({ lcp: Math.round(last.startTime) })
    }).observe({ type: 'largest-contentful-paint', buffered: true })
  } catch {
    /* 浏览器不支持 */
  }

  try {
    let cls = 0
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        const e = entry as PerformanceEntry & {
          hadRecentInput?: boolean
          value?: number
        }
        if (e.hadRecentInput) continue
        cls += e.value || 0
      }
      onReport({ cls })
    }).observe({ type: 'layout-shift', buffered: true })
  } catch {
    /* 浏览器不支持 */
  }

  try {
    new PerformanceObserver((list) => {
      const first = list.getEntries()[0] as PerformanceEntry & {
        startTime: number
        interactionId?: number
      }
      if (first) {
        // interactionId 存在 → 按 INP 语义处理（Chrome 96+）
        onReport(first.interactionId ? { inp: Math.round(first.startTime) } : { fid: Math.round(first.startTime) })
      }
    }).observe({ type: 'first-input', buffered: true })
  } catch {
    /* 浏览器不支持 */
  }

  try {
    const nav = performance.getEntriesByType('navigation')[0] as
      | PerformanceNavigationTiming
      | undefined
    if (nav) onReport({ ttfb: Math.round(nav.responseStart) })
  } catch {
    /* 浏览器不支持 */
  }
}

function deliver(report: VitalsReport, opts: VitalsOptions): void {
  if (!opts.reportUrl) return
  const body = JSON.stringify(report)
  try {
    if (opts.useBeacon !== false && navigator.sendBeacon) {
      navigator.sendBeacon(
        opts.reportUrl,
        new Blob([body], { type: 'application/json' }),
      )
      return
    }
    void fetch(opts.reportUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body,
      keepalive: true,
    })
  } catch {
    /* 上报失败静默 */
  }
}

export function initVitals(options: VitalsOptions = {}): void {
  const reportUrl = options.reportUrl !== undefined ? options.reportUrl : REPORT_URL
  const opts: VitalsOptions = { reportUrl, useBeacon: options.useBeacon }
  const collected: Partial<VitalsReport> = {}
  let sent = false

  const flush = () => {
    if (sent) return
    sent = true
    const report: VitalsReport = {
      ...collected,
      url: window.location.pathname + window.location.search,
      sentAt: new Date().toISOString(),
      effectiveType: (
        navigator as unknown as { connection?: { effectiveType?: string } }
      ).connection?.effectiveType,
    }
    deliver(report, opts)
  }

  const onReport = (partial: Partial<VitalsReport>) => {
    Object.assign(collected, partial)
    // LCP 与 TTFB 齐备即上报一次（避免重复）
    if (collected.lcp && collected.ttfb) flush()
  }

  nativeCollect(onReport)

  // 兜底：最长 5s 后上报一次（覆盖 LCP 偏晚场景）
  window.setTimeout(flush, 5000)
  // 页面隐藏时立即冲刷（sendBeacon 最可靠时机）
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') flush()
  })
}

export default initVitals