// apps/user-web/src/plugins/vitals.ts
// 026 T033 — Web Vitals 采集（FR-21）
//
// 采集 LCP / FID / INP / CLS / TTFB 并上报后端。
// 使用原生 PerformanceObserver 实现（零依赖，不阻塞构建）；生产建议安装
// `web-vitals` 后把 `nativeCollect()` 替换为三行等价 import，上报管道无需改动。
//
// 用法：import { initVitals } from './vitals' ; initVitals({ reportUrl: '/portal-api/metrics/vitals' })
// 上报走 navigator.sendBeacon；端点可由 VITE_VITALS_REPORT_URL 覆盖，未配置则只采集不上报。

export interface VitalsReport {
  lcp?: number
  fid?: number
  inp?: number
  cls?: number
  ttfb?: number
  url: string
  sentAt: string
  effectiveType?: string
}

export interface VitalsOptions {
  reportUrl?: string
  useBeacon?: boolean
}

const REPORT_URL = (import.meta.env.VITE_VITALS_REPORT_URL as string | undefined) || ''

function nativeCollect(onReport: (r: Partial<VitalsReport>) => void): void {
  try {
    new PerformanceObserver((list) => {
      const entries = list.getEntries()
      const last = entries[entries.length - 1] as PerformanceEntry & { startTime: number }
      if (last) onReport({ lcp: Math.round(last.startTime) })
    }).observe({ type: 'largest-contentful-paint', buffered: true })
  } catch {
    /* 浏览器不支持 */
  }

  try {
    let cls = 0
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        const e = entry as PerformanceEntry & { hadRecentInput?: boolean; value?: number }
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
      const first = list.getEntries()[0] as PerformanceEntry & { startTime: number; interactionId?: number }
      if (first) {
        onReport(first.interactionId ? { inp: Math.round(first.startTime) } : { fid: Math.round(first.startTime) })
      }
    }).observe({ type: 'first-input', buffered: true })
  } catch {
    /* 浏览器不支持 */
  }

  try {
    const nav = performance.getEntriesByType('navigation')[0] as PerformanceNavigationTiming | undefined
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
      navigator.sendBeacon(opts.reportUrl, new Blob([body], { type: 'application/json' }))
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
      effectiveType: (navigator as unknown as { connection?: { effectiveType?: string } }).connection?.effectiveType,
    }
    deliver(report, opts)
  }

  const onReport = (partial: Partial<VitalsReport>) => {
    Object.assign(collected, partial)
    if (collected.lcp && collected.ttfb) flush()
  }

  nativeCollect(onReport)
  window.setTimeout(flush, 5000)
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') flush()
  })
}

export default initVitals