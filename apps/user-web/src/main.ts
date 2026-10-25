import { createApp } from 'vue'
import App from './App.vue'
import { initVitals } from './plugins/vitals'
import './style.css'

// /research 子路由（竞品深度调研，产品经理拍板的接入形态）：无 vue-router，按路径分流；
// nginx try_files 对 /research 回 index.html，由这里挂载对应页面。
const isResearch = /^\/research(\/|$)/.test(window.location.pathname)

const storedThemeMode = localStorage.getItem('askai.theme-mode') || 'system'
const startsDark = storedThemeMode === 'dark'
  || (storedThemeMode === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches)
document.documentElement.classList.toggle('theme-dark', startsDark)
document.documentElement.style.colorScheme = startsDark ? 'dark' : 'light'

// 026 T033: 采集 LCP/FID/CLS/TTFB 并上报（FR-21）。端点可用 VITE_VITALS_REPORT_URL 覆盖。
initVitals({ reportUrl: (import.meta.env.VITE_VITALS_REPORT_URL as string | undefined) || '/portal-api/metrics/vitals' })

if (isResearch) {
    void import('./research/ResearchPage.vue').then((m) => createApp(m.default).mount('#app'))
} else {
    createApp(App).mount('#app')
}
