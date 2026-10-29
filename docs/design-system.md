# MOGO 设计规范系统

> 唯一权威文档。新增页面、改造旧页面、评审 UI 时以本文为准。
> 配套可执行检查：`node scripts/check_design_tokens.mjs`（加 `--strict` 供 CI 使用）。

## 1. 这套系统解决什么问题

平台有两个前端 SPA，历史上各自演进，累积了三类系统性偏差：

| 问题 | 表现 | 根因 |
| --- | --- | --- |
| 布局失效 | 门户上架 / 门户审批页无内边距、无间距，内容贴边 | `admin-web` **未安装 Tailwind**，但模板里写了 `p-4 space-y-4 text-gray-400`，这些类完全不生效 |
| 深色主题失效 | 深色下出现白底黑字卡片、灰字不可读 | 每个页面各自硬编码十六进制色值，深色只在少数页面手写了 `html.dark` 覆盖 |
| 风格割裂 | 资产评级页自写 `h2` 标题 + 四色分布块；其他页用 `PageIntro` | 缺少统一的页面骨架与令牌层，页面各自造轮子 |

本规范用三层结构收敛：**令牌（tokens）→ 语义类（base）→ 组件（naive-ui 桥接）**。
页面只允许消费令牌与语义类，不再自己定义颜色。

## 2. 文件结构

```
apps/admin-web/src/
  styles/tokens.css      设计令牌：浅 / 深两套语义变量（唯一色值来源）
  styles/base.css        组件层：页面骨架、卡片、工具栏、文本层级、语义徽章
  styles.css             入口：@import tokens + base，仅保留 app-shell
  theme/naive.ts         naive-ui 主题桥接：overrides 全部引用 var(--mg-*)
  components/PageIntro.vue  页面头部（标题 / 描述 / 标签 / 操作区）

apps/user-web/src/
  styles/tokens.css      与 admin-web 同源（改一侧必须同步另一侧）
  styles/base.css        同源，保留 user-web 的布局差异
  style.css              tailwind 指令 + 「遗留兼容层」（深色下把 tailwind 颜色类映射到令牌）
  theme/naive.ts         同源，含 user-web 特有的 Switch / Input 配置
```

> 两个 SPA 独立构建，没有共享包。令牌文件以「同源复制」方式共享，**修改任一侧必须同步另一侧**，这是当前约束下成本最低的做法。

## 3. 令牌体系

命名规则：`--mg-<类别>-<语义>[-<变体>]`。前缀 `mg` 避免与 naive-ui（`--n-*`）和 Tailwind 冲突。

### 3.1 分层

| 层 | 用途 | 是否允许业务代码引用 |
| --- | --- | --- |
| L1 palette `--mg-palette-*` | 原始色阶 | **禁止**，仅 tokens.css 内部使用 |
| L2 semantic `--mg-bg-*` `--mg-text-*` `--mg-border-*` `--mg-brand-*` `--mg-{success,warning,danger,info,neutral}-*` | 语义色 | 允许，页面唯一可用层 |
| L3 component `--mg-radius-*` `--mg-space-*` `--mg-font-*` `--mg-shadow-*` | 形状 / 间距 / 字体 / 阴影 | 允许 |

### 3.2 核心语义变量

| 变量 | 用途 |
| --- | --- |
| `--mg-bg-app` | 页面底色 |
| `--mg-bg-surface` | 卡片 / 弹层 / 表格表面 |
| `--mg-bg-surface-hover` | 表面 hover |
| `--mg-bg-subtle` | 浅色分区块、表头 |
| `--mg-bg-inset` | 内嵌区域（代码块、只读块） |
| `--mg-text-1 / -2 / -3` | 主文本 / 次要文本 / 说明与占位（**只有三级**） |
| `--mg-text-disabled` | 禁用态文本 |
| `--mg-border` / `--mg-border-strong` / `--mg-divider` | 常规边框 / 强调边框 / 分隔线 |
| `--mg-brand` / `-hover` / `-pressed` | 品牌主色（浅色 `#366AFF`，深色提亮为 `#6B93FF`） |
| `--mg-brand-soft` / `-soft-border` / `-brand-text` | 品牌浅底、浅底描边、浅底上的文字 |
| `--mg-{success,warning,danger,info,neutral}-{text,bg,border}` | 状态三元组，成对使用 |
| `--mg-level-l1..l4-{bg,text}` | 资产评级 L1–L4（L4 为最高级） |
| `--mg-radius-xs..xl` / `--mg-radius-pill` | 圆角阶梯（4 / 6 / 10 / 14 / 18 / 999） |
| `--mg-space-1..10` | 间距阶梯（4px 基准） |
| `--mg-font-size-xs..3xl` | 字号阶梯（12 / 13 / 14 / 16 / 20 / 26 / 30） |

### 3.3 使用示例

```css
/* 正确 */
.my-panel {
  background: var(--mg-bg-surface);
  border: 1px solid var(--mg-border);
  border-radius: var(--mg-radius-lg);
  padding: var(--mg-space-4);
  color: var(--mg-text-1);
}

/* 错误：硬编码色值，深色主题下必然失效 */
.my-panel {
  background: #fff;
  border: 1px solid #e6ebf5;
  color: #101c3d;
}
```

## 4. 主题机制

### 4.1 模式

三档：`light` / `dark` / `system`（跟随系统）。持久化键：

- admin-web：`localStorage['askai-admin-theme']`
- user-web：`localStorage['askai.theme-mode']`

### 4.2 切换入口

- **admin-web**：顶栏右侧月亮 / 太阳图标下拉（浅色 / 深色 / 跟随系统）。逻辑在 `composables/theme.ts`，图标在 `layouts/BasicLayout.vue`。
- **user-web**：个人设置面板内的主题分段控件（已有）。

### 4.3 生效机制

```
用户切换 → <html> 加/去 class → tokens.css 的语义变量重定义 → 所有 var(--mg-*) 自动跟随
                                ↘ naive-ui 的 themeOverrides 本身引用 var(--mg-*)，无需重建对象
```

- admin-web 使用 `html.dark`（同时写 `data-theme`）
- user-web 使用 `html.theme-dark`
- `tokens.css` 的深色段同时命中 `html.dark, html.theme-dark`，两个 app 共用一套取值

**关键约定：组件里不需要写 `html.dark` 覆盖块。** 如果发现某处深色不对，说明它绕过了令牌，应改令牌而不是加覆盖。

## 5. 页面骨架

### 5.1 标准结构

```vue
<template>
  <div class="mg-page">
    <PageIntro :title="t('页面标题')" :description="t('一句话说明这个页面能做什么')">
      <template #actions>
        <n-button secondary :loading="loading" @click="load">{{ t('刷新') }}</n-button>
        <n-button type="primary" @click="openCreate">{{ t('新建') }}</n-button>
      </template>
    </PageIntro>

    <n-card :bordered="false" size="small" :title="t('列表')">
      <!-- 内容 -->
    </n-card>
  </div>
</template>
```

容器三选一：

| 类 | 场景 |
| --- | --- |
| `.mg-page` | 默认。居中、限宽 1440px、统一内边距 |
| `.mg-page--flush` | 需要撑满内容区高度（表格页、看板），不加限宽 |
| `.mg-page--narrow` | 表单 / 详情类窄版心（960px） |

### 5.2 语义类清单

| 类 | 用途 |
| --- | --- |
| `.mg-page-head` / `.mg-page-head__text` / `.mg-page-title` / `.mg-page-desc` / `.mg-page-actions` | 页面头部（`PageIntro` 内部已用，手写时也走这套） |
| `.mg-card` / `.mg-card__header` / `.mg-card__title` / `.mg-card__body` | 非 naive 场景的卡片表面 |
| `.mg-toolbar` / `.mg-toolbar__group` | 筛选 / 批量操作行 |
| `.mg-stat-grid` / `.mg-stat` / `.mg-stat__label` / `.mg-stat__value` / `.mg-stat__foot` | 指标卡 |
| `.mg-level-grid` / `.mg-level-cell` / `.mg-level-cell--l1..l4` | 资产评级分布 |
| `.mg-text-1` / `.mg-text-2` / `.mg-text-3` / `.mg-caption` / `.mg-mono` | 文本层级 |
| `.mg-badge` / `.mg-badge--{success,warning,danger,info}` | 非表格场景的语义标签 |

### 5.3 表格页范式

表格页统一：`PageIntro` → 筛选区（`NCard` + `NSpace` 或 `.mg-toolbar`）→ `NDataTable`。
表格内不要写 Tailwind 类（admin-web 未安装），次要说明文字用 `.mg-caption`。

## 6. 组件规范

### 6.1 组件库

**只用 naive-ui**。不引入第二套组件库；图标用内联 SVG 或 `@vicons`（user-web 已装）。

### 6.2 状态色映射

| 业务语义 | naive `type` | 令牌 |
| --- | --- | --- |
| 成功 / 已上架 / 已开通 | `success` | `--mg-success-*` |
| 进行中 / 待处理 | `info` | `--mg-info-*` |
| 警告 / 已回收 / 降级风险 | `warning` | `--mg-warning-*` |
| 失败 / 已拒绝 / 停用 | `error` | `--mg-danger-*` |
| 中性 / 未知 / 已下架 | `default` | `--mg-neutral-*` |

### 6.3 资产评级

L1 基础（灰）→ L2 蓝 → L3 橙 → L4 绿（最高级）。分布块用 `.mg-level-cell--l{1..4}`，
表格内标签用 `NTag` + 对应语义 `type`，不要自造颜色。

## 7. 禁止事项

1. 页面 / 组件样式里写十六进制色值、`rgb()`、`rgba()`（透明度微调用 `color-mix()` + 令牌）。
2. 在 admin-web 里使用 Tailwind 工具类（未安装，类名不生效）。
3. 页面内自写 `h1/h2` 标题块代替 `PageIntro`。
4. 用 `html.dark { ... }` 逐条覆盖组件颜色（应改令牌）。
5. 在 `.vue` 里内联 `style="color: #xxx"`。
6. 新增令牌只写浅色、不写深色取值。

## 8. 巡检与 CI

```bash
node scripts/check_design_tokens.mjs           # 报告（退出码恒为 0）
node scripts/check_design_tokens.mjs --strict  # 有 error 时退出 1
node scripts/check_design_tokens.mjs --json    # 机器可读
```

规则：

| 规则 | 级别 | 含义 |
| --- | --- | --- |
| R1 | error | admin-web 出现 Tailwind 工具类（不生效） |
| R2 | error | style 段有硬编码色值，且无深色覆盖、未引用令牌（深色下必然出错） |
| R3 | warn | style 段有硬编码色值（浅色可用，无法跟随主题） |
| R4 | warn | 页面自写标题块 |
| R5 | error | `var(--mg-*)` 引用了未定义的令牌（拼错会静默失效，必须拦） |

前端改动提交前先跑一遍，`error` 项不得新增。

## 9. 改造现状与迁移清单

### 9.1 已统一（本批次）

| 页面 | 处理 |
| --- | --- |
| 资产中心 `views/AssetsPage.vue` | 13 处无效 Tailwind 类（布局完全塌陷）→ 语义类 + scoped 令牌样式 |
| 资产评级 `trust-ratings/TrustRatingPage.vue` | 自写标题块 → `PageIntro`；四色分布块 → `.mg-level-*`；33 处硬编码色 → 令牌；容器 → `.mg-page--flush` |
| 门户上架 `portal/PortalListingPage.vue` | 无效 Tailwind（`p-4 space-y-4` 等）→ `.mg-page` / `.mg-caption` |
| 门户审批 `portal/PortalApprovalPage.vue` | 同上，含弹层与表格内联类 |
| 门户目录 `components/portal/PortalCatalog.vue` | 硬编码色 + 手写 `.theme-dark` 覆盖 → 令牌；标题块 → `.mg-page-head` |
| 我的申领 `components/portal/MyRequests.vue` | 次要文本 → `.mg-caption`，间距令牌化 |
| 资产详情 `components/portal/PortalDetail.vue` | 硬编码色 → 令牌，文本层级统一 |
| 应用外壳 `layouts/BasicLayout.vue` | 删除 12 段重复的 `html.dark` 覆盖，全部走令牌；顶栏新增主题切换入口 |
| 页面头部 `components/PageIntro.vue` | 升级为规范头部（支持 `#actions` 插槽），11 个页面自动受益 |

### 9.2 待迁移（按优先级）

巡检当前基线：**error 112 / warn 23**（改造前 error 113）。优先处理 error 中「高曝光 + 深色下明显破相」的页面：

1. `views/dashboard/DashboardPage.vue`（87 处硬编码色）、`views/analytics/AnalyticsPage.vue`（53 处）
2. `views/knowledge/KnowledgeDocumentsPage.vue`（90 处）、`views/models/ModelsPage.vue`（42 处）
3. `views/skills/SkillConfigPage.vue`（216 处，两个 app 中最多）
4. `components/setup/*`（首装流程 8 个组件，共约 100 处）
5. `components/settings/ShortcutSettingsPanel.vue`（27 处）
6. 登录 / 邀请页（`views/auth/*`，深色下目前基本不可用）
7. `views/tools/*`、`views/organizations/*`（各 15–40 处）

迁移方式固定为三步：**替换色值为令牌 → 删除 `html.dark` 覆盖块 → 跑巡检确认该文件不再命中 R2/R3**。

## 10. 相关文件

- 令牌：`apps/admin-web/src/styles/tokens.css`、`apps/user-web/src/styles/tokens.css`
- 语义类：`apps/{admin,user}-web/src/styles/base.css`
- 主题桥接：`apps/{admin,user}-web/src/theme/naive.ts`
- 巡检脚本：`scripts/check_design_tokens.mjs`
- 前端 SFC 编译校验：`node scripts/check_sfc.mjs [files...]`
