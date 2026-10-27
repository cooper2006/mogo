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

// 026 T033: 采集 LCP/FID/CLS/TTFB（FR-21）。
// 上报端点必须显式配置 VITE_VITALS_REPORT_URL：后端目前没有 /metrics/vitals 接收端点
// （T033 只落地了采集侧），而生产 nginx 也没有 /portal-api/ 反代，硬编码默认值只会
// 让每个页面刷一条 `POST /portal-api/metrics/vitals 405`（落到 user-web 静态站）。
// 补齐接收端点后配一个环境变量即可开启，无需再改代码。
const vitalsReportUrl = (import.meta.env.VITE_VITALS_REPORT_URL as string | undefined)?.trim()
if (vitalsReportUrl) initVitals({ reportUrl: vitalsReportUrl })

if (isResearch) {
    void import('./research/ResearchPage.vue').then((m) => createApp(m.default).mount('#app'))
} else {
    createApp(App).mount('#app')
}
