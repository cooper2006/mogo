/**
 * 017 three-scope memory — admin-web 治理 API 客户端（T030 共用契约 · admin 侧）。
 *
 * 事实来源：specs/017-three-scope-memory/design-2026-11-05-project-department-scopes.md
 *   §7.4 两端共用契约、§9.1 接口与契约变更。
 *
 * 本文件与 apps/user-web/src/api/memories.ts 是一份「镜像」共用契约：两个 app
 * 独立构建（各自的 tsconfig / 路径别名 / node_modules），无法物理 import 同一
 * 文件，因此以同名类型、同字段、同分页/错误语义保持两端一致。改动时请同步两侧。
 *
 * ── 关键约定（不要自行更改）──────────────────────────────────────────
 *  · 范围枚举只有 personal / project / department（D4 直接改名，无兼容层，
 *    不出现 workspace / org）。
 *  · 项目成员来源只有 049 projects.member_user_ids；不存在 project_members
 *    集合，也不假定 sharing_enabled 字段。
 *  · project_id="default" 不可承载项目记忆，前端禁用/提示。
 *  · 记忆不挂 /assets（045 排除项）；地址形如 mogo://memory/{scope}/...。
 *  · 不可见一律 404：前端按「无权限 / 不存在」显示，不泄露内容（T030）。
 *  · 响应 { code, message, data }；错误遵循 025 ErrorResponse（含 trace_id / detail）。
 *  · admin 分页 PageParams：page / page_size / total（user 侧用 cursor / limit）。
 *
 * ── TODO(backend) 治理端点缺口 ──────────────────────────────────────
 *  下列 admin-api 治理端点为 design §9.1「017 新增」目标契约，当前后端可能尚未
 *  提供（跨租户列表 / 审批 / 策略 / stats / 归档）。前端已按 §9.1 契约定义函数，
 *  待后端上线即可直接工作；不要在前端伪造数据，也不要改后端 Python 文件。
 *  检索过的关键词（均无命中，确认缺口）：
 *    "memories/admin/list"、"memories/admin/stats"、"memories/admin/approvals"、
 *    "memories/admin/policies"、"memories/admin/{id}/archive"、
 *    "get_current_admin_user" + "memory:read" / "memory:manage" / "memory:approve"。
 *  治理动作由后端 feature_audit_bridge 落 feature="017" 的 memory.* 审计
 *  （§9.4），前端只调用约定端点，不重写审计桥逻辑。
 */
import { apiClient } from './client';

// ── 共用契约（与 user-web 侧镜像）─────────────────────────────────────
export type MemoryScope = 'personal' | 'project' | 'department';
export const MEMORY_SCOPES: readonly MemoryScope[] = ['personal', 'project', 'department'] as const;
export type MemoryStatus = 'active' | 'archived';
/** §9.1 回显 resolved_from（D4 已移除 legacy_alias）。 */
export type MemoryResolvedFrom = 'explicit' | 'default' | 'default_fallback' | 'sediment';
export const DEFAULT_PROJECT_ID = 'default';

export function isDefaultProject(projectId?: string | null): boolean {
  return (projectId ?? '') === DEFAULT_PROJECT_ID;
}
/** D4：出现旧拼写直接拒绝，不做静默转换（后端返回 400 scope_invalid / 404）。 */
export function isLegacyScope(value: string): boolean {
  return value === 'workspace' || value === 'org';
}

export interface MemoryItem {
  memory_id: string;
  scope: MemoryScope;
  actual_scope?: MemoryScope;
  resolved_from?: MemoryResolvedFrom;
  project_id?: string;
  project_owner_id?: string;
  department_id?: string;
  owner_id?: string;
  tenant_id?: string;
  content?: string;
  l0_summary?: string;
  l1_overview?: string;
  l2_raw?: string;
  tierable?: boolean;
  addr?: string;
  source_session_id?: string;
  source_type?: string;
  status?: MemoryStatus;
  archived?: boolean;
  promotion_status?: string;
  pending_department_id?: string;
  invalidated?: boolean;
  invalidated_reason?: string;
  created_at?: string;
  updated_at?: string;
  last_accessed_at?: string;
  provenance?: Record<string, unknown>;
  retrieval_trace?: unknown[];
  audit?: unknown[];
}

/** { code, message, data } 解包；兼容个别裸返回端点。 */
function dataOf<T>(payload: any): T {
  return (payload?.data ?? payload) as T;
}

/** 025 ErrorResponse 归一化。不可见即 404 → notFound=true，前端不回显 detail。 */
export interface MemoryApiError {
  status: number;
  code?: string;
  detail?: string;
  traceId?: string;
  notFound: boolean;
}
export function normalizeMemoryError(error: any): MemoryApiError {
  const status = Number(error?.response?.status ?? 0);
  const body = error?.response?.data ?? {};
  return {
    status,
    code: body?.code,
    detail: body?.detail,
    traceId: body?.trace_id,
    notFound: status === 404,
  };
}
/** 面向用户的错误文案：404 统一「不存在或无权查看」，不泄露内容。 */
export function memoryErrorText(error: any, fallback = '操作失败'): string {
  const e = normalizeMemoryError(error);
  if (e.notFound) return '内容不存在或你无权查看';
  return e.detail || fallback;
}

/**
 * project_id + project_owner_id 消歧回显项目名（§7.2 / §9.1）。
 * 049 项目视图只读；查不到 → 「已归档 / 已删除」。
 */
export interface MemoryProjectView {
  id: string;
  title: string;
  user_id?: string;
  member_user_ids?: string[];
}
export function resolveProjectName(
  projects: MemoryProjectView[],
  projectId?: string | null,
  projectOwnerId?: string | null,
): string {
  if (!projectId) return '';
  const match = projects.find((p) => p.id === projectId && (!projectOwnerId || p.user_id === projectOwnerId))
    || projects.find((p) => p.id === projectId);
  return match?.title || '已归档 / 已删除';
}

// ── 分页（§7.4：admin 用 page / page_size / total）────────────────────
export interface AdminPageParams {
  page: number;
  page_size: number;
  scope?: MemoryScope | '';
  tenant_id?: string;
  status?: MemoryStatus | '';
  keyword?: string;
}
export interface AdminPageResult<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}
/** 指标卡数据源（§7.2：总数 / 按 scope 分布 / 近日新增 / 待审批 等）。 */
export interface MemoryStats {
  total: number;
  by_scope: Partial<Record<MemoryScope, number>>;
  recent_added: number;
  pending_approval: number;
  department_coverage?: number;
  pending_decay_archive?: number;
}

// ── 治理端点（§9.1 admin-api；TODO 待后端提供）──────────────────────
const ADMIN_BASE = '/api/v1/memories/admin';

export async function fetchAdminMemories(params: AdminPageParams): Promise<AdminPageResult<MemoryItem>> {
  const { data } = await apiClient.get(`${ADMIN_BASE}/list`, { params });
  const d = dataOf<any>(data);
  return {
    items: d?.items ?? d?.memories ?? [],
    total: Number(d?.total ?? 0),
    page: Number(d?.page ?? params.page),
    page_size: Number(d?.page_size ?? params.page_size),
  };
}

export async function fetchAdminMemory(id: string): Promise<MemoryItem> {
  const { data } = await apiClient.get(`${ADMIN_BASE}/${encodeURIComponent(id)}`);
  return dataOf<MemoryItem>(data);
}

export async function fetchAdminMemoryStats(): Promise<MemoryStats> {
  const { data } = await apiClient.get(`${ADMIN_BASE}/stats`);
  return dataOf<MemoryStats>(data);
}

export async function archiveAdminMemory(id: string, reason: string): Promise<void> {
  await apiClient.post(`${ADMIN_BASE}/${encodeURIComponent(id)}/archive`, { reason });
}
export async function restoreAdminMemory(id: string, reason: string): Promise<void> {
  await apiClient.post(`${ADMIN_BASE}/${encodeURIComponent(id)}/restore`, { reason });
}
/** 删除需 full_access_admin + 审计（§7.2）。 */
export async function deleteAdminMemory(id: string, reason: string): Promise<void> {
  await apiClient.post(`${ADMIN_BASE}/${encodeURIComponent(id)}/delete`, { reason });
}
/**
 * 批量归档（§7.2 新增能力）。§9.1 未列批量端点，不编造路径：以单条 archive
 * 端点循环落地；后端若后续提供批量端点，可在此替换。
 */
export async function batchArchiveAdminMemories(ids: string[], reason: string): Promise<void> {
  for (const id of ids) await archiveAdminMemory(id, reason);
}

/** 提升审批（§9.1 promote：target_scope=department + department_id）。 */
export interface MemoryApprovalPayload {
  memory_id: string;
  target_scope: 'department';
  department_id: string;
  reason?: string;
}
export async function submitMemoryApproval(payload: MemoryApprovalPayload): Promise<MemoryItem> {
  const { data } = await apiClient.post(`${ADMIN_BASE}/approvals`, payload);
  return dataOf<MemoryItem>(data);
}

// ── T035 提升审批状态机（pending 队列 + 通过 / 驳回）──────────────────
export interface PromotionResolution {
  department_id?: string;
  reason?: string;
}
/** 待审批队列：promotion_status == "pending" 的记忆列表。 */
export async function fetchAdminPendingApprovals(params: AdminPageParams): Promise<AdminPageResult<MemoryItem>> {
  const { data } = await apiClient.get(`${ADMIN_BASE}/approvals`, { params });
  const d = dataOf<any>(data);
  return {
    items: d?.items ?? d?.memories ?? [],
    total: Number(d?.total ?? 0),
    page: Number(d?.page ?? params.page),
    page_size: Number(d?.page_size ?? params.page_size),
  };
}
/** 通过：promotion_status pending → approved 并提升为 department。 */
export async function approveMemoryPromotion(id: string, payload: PromotionResolution): Promise<MemoryItem> {
  const { data } = await apiClient.post(`${ADMIN_BASE}/${encodeURIComponent(id)}/approve`, payload);
  return dataOf<MemoryItem>(data);
}
/** 驳回：promotion_status pending → rejected（scope 不变）。 */
export async function rejectMemoryPromotion(id: string, payload: PromotionResolution): Promise<MemoryItem> {
  const { data } = await apiClient.post(`${ADMIN_BASE}/${encodeURIComponent(id)}/reject`, payload);
  return dataOf<MemoryItem>(data);
}

// ── T037 离职 / 删号显式失效 治理端点 ────────────────────────────────
export interface OffboardPayload {
  user_id: string;
  reason?: string;
}
export async function offboardUserMemories(payload: OffboardPayload): Promise<{ success: boolean; invalidated_count: number }> {
  const { data } = await apiClient.post(`${ADMIN_BASE}/governance/offboard`, payload);
  return dataOf<{ success: boolean; invalidated_count: number }>(data);
}
export interface ProjectArchiveInvalidationPayload {
  project_id: string;
  project_owner_id: string;
  reason?: string;
}
export async function archiveProjectMemories(payload: ProjectArchiveInvalidationPayload): Promise<{ success: boolean; invalidated_count: number }> {
  const { data } = await apiClient.post(`${ADMIN_BASE}/governance/project-archive`, payload);
  return dataOf<{ success: boolean; invalidated_count: number }>(data);
}

// ── T027 可见范围 / 策略 / 配额（§9.5 配置 + §7.2）───────────────────
export interface VisibilityRule {
  department_ids: string[];
  position_role_ids: string[];
  employee_user_ids: string[];
  include_descendants: boolean;
}
export interface MemoryQuota {
  per_user: number;
  per_project: number;
  per_department: number;
}
export interface MemoryPolicies {
  decay_days: number;
  cleanup_policy: 'archive' | 'delete';
  summary_refresh_days: number;
  l2_hard_max_bytes: number;
  archived_project_retrievable: boolean;
  visibility: VisibilityRule;
  quota: MemoryQuota;
}
export function defaultMemoryPolicies(): MemoryPolicies {
  return {
    decay_days: 30,
    cleanup_policy: 'archive',
    summary_refresh_days: 30,
    l2_hard_max_bytes: 0,
    archived_project_retrievable: false,
    visibility: { department_ids: [], position_role_ids: [], employee_user_ids: [], include_descendants: true },
    quota: { per_user: 0, per_project: 0, per_department: 0 },
  };
}
export async function fetchMemoryPolicies(): Promise<MemoryPolicies> {
  const { data } = await apiClient.get(`${ADMIN_BASE}/policies`);
  return dataOf<MemoryPolicies>(data);
}
export async function updateMemoryPolicies(payload: MemoryPolicies): Promise<MemoryPolicies> {
  const { data } = await apiClient.put(`${ADMIN_BASE}/policies`, payload);
  return dataOf<MemoryPolicies>(data);
}

/**
 * 管理端项目列表（§9.1「049 已修复，017 只做回归」）——仅用于 project_id +
 * project_owner_id 消歧回显项目名，不做成员编辑（归 049）。
 * TODO(backend): 响应结构待与 traffic-allocations/projects-with-usage 对齐；
 * 这里做防御性映射，只取项目名 / owner / member_user_ids。
 */
export async function listAdminProjects(): Promise<MemoryProjectView[]> {
  const { data } = await apiClient.get('/api/v1/traffic-allocations/projects-with-usage');
  const d = dataOf<any>(data);
  const list = Array.isArray(d) ? d : (d?.items ?? d?.projects ?? []);
  return (Array.isArray(list) ? list : []).map((p: any) => ({
    id: String(p.id ?? p.project_id ?? ''),
    title: String(p.title ?? p.name ?? p.project_name ?? ''),
    user_id: p.user_id ?? p.owner_id,
    member_user_ids: Array.isArray(p.member_user_ids) ? p.member_user_ids : [],
  }));
}
