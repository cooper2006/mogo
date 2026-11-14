import type { RouteRecordRaw } from 'vue-router';
import { AccountGroupsIcon } from '@/icons/AccountGroupsIcon';
import { DashboardBarsIcon } from '@/icons/DashboardBarsIcon';
import { ModelsCenterIcon } from '@/icons/ModelsCenterIcon';
import { KnowledgeDocumentsIcon } from '@/icons/KnowledgeDocumentsIcon';
import { TokenStatsIcon } from '@/icons/TokenStatsIcon';
import { TrafficAllocationIcon } from '@/icons/TrafficAllocationIcon';
import { UserManagementIcon } from '@/icons/UserManagementIcon';
import { ToolsMcpIcon } from '@/icons/ToolsMcpIcon';
import { DshPluginsIcon } from '@/icons/DshPluginsIcon';
import { SkillsManagerIcon } from '@/icons/SkillsManagerIcon';
import { SettingsIcon } from '@/icons/SettingsIcon';
import { PositionRolesIcon } from '@/icons/PositionRolesIcon';
import { SystemAuditIcon } from '@/icons/SystemAuditIcon';
import { HookRulesIcon } from '@/icons/HookRulesIcon';
import { OntologyIcon } from '@/icons/OntologyIcon';
import { ResourceCenterIcon } from '@/icons/ResourceCenterIcon';
import { ArchiveOutline, PulseOutline } from '@vicons/ionicons5';

export const appRoutes: RouteRecordRaw[] = [
  {
    path: '/setup',
    name: 'Setup',
    component: () => import('@/views/auth/SetupPage.vue'),
    meta: {
      title: '系统初始化',
      hideInMenu: true,
      public: true,
    },
  },
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/auth/LoginPage.vue'),
    meta: {
      title: '登录',
      hideInMenu: true,
    },
  },
  {
    path: '/platform/login',
    name: 'PlatformLogin',
    component: () => import('@/views/auth/PlatformLoginPage.vue'),
    meta: {
      title: '平台管理员登录',
      hideInMenu: true,
      public: true,
    },
  },
  {
    path: '/invite/accept',
    name: 'InviteAccept',
    component: () => import('@/views/auth/InviteAcceptPage.vue'),
    meta: {
      title: '接受邀请',
      hideInMenu: true,
      public: true,
    },
  },
  {
    path: '/',
    component: () => import('@/layouts/BasicLayout.vue'),
    children: [
      {
        path: '',
        redirect: '/dashboard',
      },
      {
        path: '/dashboard',
        name: 'Dashboard',
        component: () => import('@/views/dashboard/DashboardPage.vue'),
        meta: { title: '工作台', icon: DashboardBarsIcon },
      },
      {
        path: '/profile',
        name: 'Profile',
        component: () => import('@/views/profile/ProfilePage.vue'),
        meta: { title: '个人中心', hideInMenu: true },
      },
      {
        // 技能列表已归入「资产中心」二级菜单（见下方 /assets children）；
        // 详情页继续保留 /skills/:id/... 的既有 URL。
        path: '/skills/:id/config',
        name: 'SkillConfig',
        component: () => import('@/views/skills/SkillConfigPage.vue'),
        meta: { title: 'Skill配置', hideInMenu: true },
      },
      {
        path: '/skills/:id/canary',
        name: 'SkillCanaryConfig',
        component: () => import('@/views/skills/SkillCanaryConfigPage.vue'),
        meta: { title: '灰度发布', hideInMenu: true },
      },
      // 045: 资产评级已并入「资产中心」的二级菜单，旧路径保留重定向（书签兼容）
      {
        path: '/trust-ratings',
        redirect: '/assets/ratings',
        meta: { hideInMenu: true },
      },
      {
        path: '/dsh-plugins',
        redirect: '/resources/dsh-plugins',
        meta: { hideInMenu: true },
      },
      // 「工具与 MCP」「连接器市场」已归入「资产中心」二级菜单（见下方 /assets children）；
      // 工具编辑页继续保留 /tools/new、/tools/:id/edit 的既有 URL。
      {
        // 054: 资源中心 —— 插件/记忆/模型/知识/本体 的统一一级入口
        // 父路由不设 component，子页面直接渲染到 BasicLayout 的 router-view；
        // 资源中心没有独立概览页，一级菜单点击时跳到「模型中心」。
        path: '/resources',
        redirect: '/resources/models',
        meta: { title: '资源中心', icon: ResourceCenterIcon },
        children: [
          {
            path: 'dsh-plugins',
            name: 'ResourceDshPlugins',
            component: () => import('@/views/dsh-plugins/DshPluginsPage.vue'),
            meta: { title: 'dshPlugins.title', icon: DshPluginsIcon },
          },
          {
            path: 'memories',
            name: 'ResourceMemories',
            component: () => import('@/views/memories/MemoriesPage.vue'),
            meta: { title: '记忆管理', icon: SkillsManagerIcon },
          },
          {
            path: 'models',
            name: 'ResourceModels',
            component: () => import('@/views/models/ModelsPage.vue'),
            meta: { title: '模型中心', icon: ModelsCenterIcon },
          },
          {
            path: 'knowledge/documents',
            name: 'ResourceKnowledgeDocuments',
            component: () => import('@/views/knowledge/KnowledgeDocumentsPage.vue'),
            meta: { title: '知识文档', icon: KnowledgeDocumentsIcon },
          },
          {
            path: 'knowledge/documents/:id',
            name: 'ResourceKnowledgeDocumentDetail',
            component: () => import('@/views/knowledge/KnowledgeDocumentPreviewPage.vue'),
            meta: { title: '文档详情', hideInMenu: true },
          },
          {
            path: 'ontologies',
            name: 'ResourceOntologies',
            component: () => import('@/views/ontologies/OntologyCatalogPage.vue'),
            meta: { title: '本体授权', icon: OntologyIcon },
          },
          {
            // 009: 钩子规则归入「资源中心」二级菜单，绝对路径保留 /hooks/rules 既有 URL
            path: '/hooks/rules',
            name: 'HookRules',
            component: () => import('@/views/hooks/HookRulesPage.vue'),
            meta: { title: '钩子规则', icon: HookRulesIcon },
          },
          {
            // 053: 广场模板分发现归入「资源中心」二级菜单（原在资产中心）。
            // 用绝对路径保留 /assets/templates 既有 URL、书签，以及 055 菜单配置里的节点 key。
            path: '/assets/templates',
            name: 'AssetTemplates',
            component: () => import('@/views/templates/TemplateManagePage.vue'),
            meta: { title: '模板管理' },
          },
        ],
      },
      {
        path: '/memories',
        redirect: '/resources/memories',
        meta: { hideInMenu: true },
      },
      {
        path: '/tools/new',
        name: 'ToolCreate',
        component: () => import('@/views/tools/ToolEditPage.vue'),
        meta: { title: '新增工具连接', hideInMenu: true },
      },
      {
        path: '/tools/:id/edit',
        name: 'ToolEdit',
        component: () => import('@/views/tools/ToolEditPage.vue'),
        meta: { title: '编辑工具连接', hideInMenu: true },
      },
      {
        path: '/employees',
        name: 'Employees',
        component: () => import('@/views/employees/EmployeeManagePage.vue'),
        meta: { title: '数字员工', icon: SkillsManagerIcon },
      },
      {
        path: '/employees/create',
        name: 'EmployeeCreate',
        component: () => import('@/views/employees/EmployeeEditPage.vue'),
        meta: { title: '新建数字员工', hideInMenu: true },
      },
      {
        path: '/employees/edit/:id',
        name: 'EmployeeEdit',
        component: () => import('@/views/employees/EmployeeEditPage.vue'),
        meta: { title: '编辑数字员工', hideInMenu: true },
      },
      {
        path: '/models',
        redirect: '/resources/models',
        meta: { hideInMenu: true },
      },
      {
        path: '/knowledge/documents',
        redirect: '/resources/knowledge/documents',
        meta: { hideInMenu: true },
      },
      {
        path: '/knowledge/documents/:id',
        redirect: '/resources/knowledge/documents/:id',
        meta: { hideInMenu: true },
      },
      {
        path: '/analytics',
        redirect: '/token-stats',
        meta: { hideInMenu: true },
      },
      {
        path: '/platform/tenants',
        name: 'PlatformTenants',
        component: () => import('@/views/platform/TenantsPage.vue'),
        meta: { title: '平台控制台', icon: SettingsIcon, platformOnly: true },
      },
      {
        path: '/platform/system-health',
        name: 'PlatformSystemHealth',
        component: () => import('@/views/platform/SystemHealthPage.vue'),
        meta: { title: '服务健康', hideInMenu: true, platformOnly: true },
      },
      {
        path: '/organizations/accounts',
        name: 'OrganizationAccounts',
        component: () => import('@/views/organizations/OrganizationAccountsPage.vue'),
        meta: { title: '账号组与账号', icon: AccountGroupsIcon, menuGroup: 'organizations' },
      },
      {
        path: '/organizations/users',
        name: 'OrganizationUsers',
        component: () => import('@/views/organizations/OrganizationUsersPage.vue'),
        meta: { title: '用户管理', icon: UserManagementIcon, menuGroup: 'organizations' },
      },
      {
        path: '/organizations/position-roles',
        name: 'PositionRoles',
        component: () => import('@/views/position-roles/PositionRolesPage.vue'),
        meta: { title: '用户岗位角色', icon: PositionRolesIcon, menuGroup: 'organizations' },
      },
      {
        path: '/organizations/traffic',
        name: 'TrafficAllocations',
        component: () => import('@/views/organizations/TrafficAllocationsPage.vue'),
        meta: { title: '流量分配', icon: TrafficAllocationIcon, menuGroup: 'organizations' },
      },
      {
        path: '/projects',
        name: 'Projects',
        component: () => import('@/views/projects/ProjectsPage.vue'),
        meta: { title: '项目管理', icon: AccountGroupsIcon, menuGroup: 'organizations' },
      },
      {
        path: '/organizations',
        redirect: '/organizations/accounts',
        meta: { hideInMenu: true },
      },
      {
        path: '/ontologies',
        redirect: '/resources/ontologies',
        meta: { hideInMenu: true },
      },
      {
        // 045: 资产中心 —— 资产相关页面的统一入口（一级菜单 + 二级子页）
        // 父路由不设 component，二级页面直接渲染到 BasicLayout 的 router-view；
        // path '' 的子路由是「资产中心」自身的概览页。
        // 技能 / 工具与 MCP / 连接器市场三类一等资产的管理页作为二级菜单归入此处，
        // 子路由用绝对路径，保留 /skills、/tools、/connectors 的既有 URL 与书签，
        // 只调整菜单层级；详情页（/skills/:id/...、/tools/:id/edit）仍在根层级。
        path: '/assets',
        meta: { title: '资产中心', icon: SkillsManagerIcon },
        children: [
          {
            path: '',
            name: 'Assets',
            component: () => import('@/views/AssetsPage.vue'),
            meta: { title: '资产中心', hideInMenu: true },
          },
          {
            path: '/skills',
            name: 'Skills',
            component: () => import('@/views/skills/SkillsPage.vue'),
            meta: { title: '技能管理', icon: SkillsManagerIcon },
          },
          {
            path: '/tools',
            name: 'Tools',
            component: () => import('@/views/tools/ToolsPage.vue'),
            meta: { title: '工具与 MCP', icon: ToolsMcpIcon },
          },
          {
            path: '/connectors',
            name: 'ConnectorMarket',
            component: () => import('@/views/connectors/ConnectorMarketPage.vue'),
            meta: { title: '连接器市场', icon: ToolsMcpIcon },
          },
          {
            // 036: L1–L4 评级与变更管理
            path: 'ratings',
            name: 'AssetRatings',
            component: () => import('@/views/trust-ratings/TrustRatingPage.vue'),
            meta: { title: '资产评级' },
          },
          {
            // 037: 上架 / 下架（即时生效，下架不撤销存量授权）
            path: 'listings',
            name: 'AssetListings',
            component: () => import('@/views/portal/PortalListingPage.vue'),
            meta: { title: '资产上架' },
          },
          {
            // 037: 申领审批（批准即写入用户级 asset:use 授权）
            path: 'approvals',
            name: 'AssetApprovals',
            component: () => import('@/views/portal/PortalApprovalPage.vue'),
            meta: { title: '资产审批' },
          },
        ],
      },
      // 037: 门户上架 / 审批已并入「资产中心」二级菜单，旧路径保留重定向（书签兼容）
      {
        path: '/portal/listings',
        redirect: '/assets/listings',
        meta: { hideInMenu: true },
      },
      {
        path: '/portal/approvals',
        redirect: '/assets/approvals',
        meta: { hideInMenu: true },
      },
      {
        // 045: 系统审计 —— 审计相关页面统一入口（一级菜单 + 二级子页）
        // 父路由不设 component，二级页面直接渲染到 BasicLayout 的 router-view；
        // path '' 的子路由是「系统审计」自身的概览页。
        path: '/audit',
        meta: { title: '系统审计', icon: SystemAuditIcon },
        children: [
          {
            path: '',
            name: 'SystemAudit',
            component: () => import('@/views/system-audit/SystemAuditPage.vue'),
            meta: { title: '系统审计', hideInMenu: true },
          },
          {
            // 038: 出站白名单（platform/tenant/tool 三层并集，默认拒绝）
            path: 'egress-allowlist',
            name: 'EgressAllowlist',
            component: () => import('@/views/egress/EgressAllowlistPage.vue'),
            meta: { title: '出站访问控制' },
          },
          {
            // 038: 出站判定审计（egress.allowed / egress.denied）
            path: 'egress-logs',
            name: 'EgressLogs',
            component: () => import('@/views/egress/EgressLogsPage.vue'),
            meta: { title: '出站审计日志' },
          },
          {
            // Token 统计归入「系统审计」二级菜单，绝对路径保留 /token-stats 既有 URL
            path: '/token-stats',
            name: 'TokenStats',
            component: () => import('@/views/analytics/AnalyticsPage.vue'),
            meta: { title: 'Token 统计', icon: TokenStatsIcon },
          },
        ],
      },
      // 旧路径保留重定向（书签兼容）
      {
        path: '/system-audit',
        redirect: '/audit',
        meta: { hideInMenu: true },
      },
      {
        // 部署状态与诊断：服务 / 镜像 / Sandbox 镜像 / 源码版本 + 复制诊断内容
        path: '/system/status',
        name: 'DeploymentStatus',
        component: () => import('@/views/deployment-status/DeploymentStatusPage.vue'),
        meta: { title: '部署状态', icon: PulseOutline, menuGroup: 'operations' },
      },
      {
        // 离线包与 Sandbox 镜像的导入导出管理（仅系统运维可见）
        path: '/system/offline-packages',
        name: 'OfflinePackages',
        component: () => import('@/views/offline-packages/OfflinePackagesPage.vue'),
        meta: { title: '离线包管理', icon: ArchiveOutline, menuGroup: 'operations', systemOperatorOnly: true },
      },
      {
        path: '/egress/allowlist',
        redirect: '/audit/egress-allowlist',
        meta: { hideInMenu: true },
      },
      {
        path: '/egress/logs',
        redirect: '/audit/egress-logs',
        meta: { hideInMenu: true },
      },
      {
        // 056: 统一审批中心（tool/portal/sop 三来源待办聚合视图）
        path: '/approvals-center',
        name: 'ApprovalCenter',
        component: () => import('@/views/approvals/ApprovalCenterPage.vue'),
        meta: { title: '审批中心', icon: SystemAuditIcon },
      },
      {
        path: '/settings',
        name: 'Settings',
        component: () => import('@/views/settings/ExternalSearchSettingsPage.vue'),
        meta: { title: '设置', icon: SettingsIcon },
      },
      {
        // 055: 菜单管理归入「权限中心」分组（硬编码分组由 menuGroup 合并），
        // 页面本身仍用 /settings/menus 路径，与设置类页面保持一致的 URL 命名空间。
        path: '/settings/menus',
        name: 'MenuManagement',
        component: () => import('@/views/settings/MenuManagePage.vue'),
        meta: { title: '菜单管理', icon: SettingsIcon, menuGroup: 'organizations' },
      },
      {
        path: '/settings/shortcuts',
        name: 'ShortcutSettings',
        component: () => import('@/views/settings/ExternalSearchSettingsPage.vue'),
        meta: { title: '快捷入口', hideInMenu: true },
      },
      {
        path: '/settings/shortcuts/default',
        name: 'ShortcutDefaultSettings',
        component: () => import('@/views/settings/ExternalSearchSettingsPage.vue'),
        meta: { title: '默认快捷入口', hideInMenu: true },
      },
      {
        path: '/settings/presentation',
        name: 'PresentationSettings',
        component: () => import('@/views/settings/ExternalSearchSettingsPage.vue'),
        meta: { title: 'PPT 生成设置', hideInMenu: true },
      },
      {
        path: '/settings/external-search',
        name: 'ExternalSearchSettings',
        component: () => import('@/views/settings/ExternalSearchSettingsPage.vue'),
        meta: { title: '设置', hideInMenu: true },
      },
      {
        path: '/settings/knowledge',
        name: 'KnowledgeSettings',
        component: () => import('@/views/settings/ExternalSearchSettingsPage.vue'),
        meta: { title: '知识库设置', hideInMenu: true },
      },
      {
        path: '/settings/page-collection',
        name: 'PageCollectionSettings',
        component: () => import('@/views/settings/ExternalSearchSettingsPage.vue'),
        meta: { title: '页面采集设置', hideInMenu: true },
      },
      {
        path: '/settings/topic-admission',
        name: 'TopicAdmissionSettings',
        component: () => import('@/views/settings/ExternalSearchSettingsPage.vue'),
        meta: { title: '任务准入', hideInMenu: true },
      },
      {
        path: '/settings/sandbox',
        name: 'SandboxSettings',
        component: () => import('@/views/settings/ExternalSearchSettingsPage.vue'),
        meta: { title: '沙箱设置', hideInMenu: true },
      },
    ],
  },
];
