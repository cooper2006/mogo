// apps/user-web/src/router/index.ts
// 026 T034 — 路由级懒加载注册表（FR-22）
//
// user-web 当前**未引入 vue-router**，由 main.ts 按路径分流（`/research` 走独立
// 应用实例，其余挂载 App.vue）。为满足 FR-22「路由级懒加载、首屏仅加载必需
// chunk」，这里提供一份路径 → 懒加载组件的注册表：
//   * `() => import(...)` 让 Vite/Rollup 把每个视图切到独立 chunk，仅当导航命中才加载；
//   * main.ts 的分流逻辑保持不动（回归风险），迁移到 vue-router 时直接把 `appRoutes`
//     作为 `routes` 传入 `createRouter({ history: createWebHistory(), routes: appRoutes })`。
//
// 依赖说明：`vue-router` 需在 package.json 安装后再启用第 2 节（当前 user-web 未安装）。

export interface LazyRoute {
  path: string
  name: string
  /** 动态 import：生产构建按路由切 chunk */
  component: () => Promise<unknown>
  meta?: { title?: string; public?: boolean }
}

/**
 * 第 1 节：按路径分流的懒加载视图（main.ts 可直接消费，与现有分流兼容）。
 */
export const lazyViews: LazyRoute[] = [
  {
    path: '/research',
    name: 'Research',
    component: () => import('../research/ResearchPage.vue'),
    meta: { title: '竞品调研' },
  },
]

/**
 * 第 2 节：迁移到 vue-router 时的完整路由表。
 * `component: () => import(...)` 即路由级懒加载；首屏入口路由只加载自身 chunk。
 */
export const appRoutes: LazyRoute[] = [
  {
    path: '/',
    name: 'Home',
    component: () => import('../App.vue'),
    meta: { title: '首页', public: true },
  },
  ...lazyViews,
]

/** 返回首屏需要预加载的 chunk 描述（供构建分析/预算脚本使用） */
export function entryChunkNames(): string[] {
  return appRoutes.map((r) => r.name)
}