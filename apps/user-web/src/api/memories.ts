/**
 * 017 three-scope memory — user-web API 客户端（T030 共用契约 · user 侧）。
 *
 * 事实来源：design §7.4 两端共用契约、§9.1 接口与契约变更、§7.3 user 端权限。
 *
 * 本文件与 apps/admin-web/src/api/memories.ts 是一份「镜像」共用契约：两个 app
 * 独立构建，无法物理 import 同一文件，故以同名类型/字段/分页与错误语义保持一致。
 *
 * ── 端点定位（不编造路径）──────────────────────────────────────────
 *  chat-api 端点真实路径 /api/v1/memories（services/chat-api/app/api/endpoints/
 *  memory.py 的 APIRouter prefix；main.py:342 `app.include_router(memory.router)`
 *  无额外 prefix）。user-web 经 vite 代理 /askai-api → localhost:8000 且去掉该
 *  前缀（vite.config.ts:83-88），故前端写 /askai-api/api/v1/memories；与既有
 *  api/directories.ts 的 /askai-api/api/v1/directories、api/sessions.ts 的
 *  /askai-api/api/projects 同款代理转发。049 项目端点为 §9.1 的
 *  GET /api/v1/projects、GET /api/v1/projects/departments。
 *
 * ── 鉴权（§7.3）────────────────────────────────────────────────────
 *  require_end_user_principal() + _assert_end_user_scope()：前端禁止在 query /
 *  body 里自报 userId / tenantId / project_owner_id 等越权字段。project_owner_id
 *  一律由服务端解析（§9.1「客户端传值忽略」）。
 *
 * ── 关键约定（不要自行更改）──────────────────────────────────────────
 *  范围枚举只有 personal / project / department（D4 无兼容层，不出现
 *  workspace / org）；project_id="default" 不可承载项目记忆；记忆不挂 /assets；
 *  不可见一律 404（前端按无权限/不存在显示，不泄露内容）；T030 两端统一分页
 *  page / page_size（user 侧保留 cursor / limit 兼容既有调用方）。
 *  项目成员唯一来源 049 projects.member_user_ids，不假定 project_members 集合
 *  或 sharing_enabled 字段；成员编辑归 049 MemberPicker，本文件不触碰。
 *
 * ── 端点状态（已收口，T030 / B4）────────────────────────────────────
 *  · 通用编辑端点 PATCH /api/v1/memories/{id} 已由 chat-api memory.py 提供：
 *    只改 content / l0_summary / l1_overview / tierable 等内容类字段，
 *    scope / *_id / owner_id / tenant_id 等授权字段由服务端解析、客户端忽略；
 *    updateMemory 现可正常工作（不再是 TODO）。
 *  · D4 一次性改名已完成：memory.py 为 personal / project / department 目标态，
 *    无 workspace_id / org 中间态、无运行时兼容层。
 *  · list 与 admin 对齐为 page / page_size；响应逐条回显 actual_scope /
 *    resolved_from（explicit|default|default_fallback|sediment），无 legacy_alias；
 *    可见性仍由服务端 visible_to / list_for_viewer(viewer=...) 保证。
 *  · promote 以 body（MemoryPromotePayload：target_scope / department_id /
 *    reason）为主，department_id 同时经 query 双发兼容只认 query 的后端。
 */
import { createApiClient } from './client';

const api = createApiClient({ timeout: 30000 });
const BASE = '/askai-api/api/v1/memories';
const PROJECTS_BASE = '/askai-api/api/v1/projects';

// ── 共用契约（与 admin-web 侧镜像）───────────────────────────────────
export type MemoryScope = 'personal' | 'project' | 'department';
export const MEMORY_SCOPES: readonly MemoryScope[] = ['personal', 'project', 'department'] as const;
export type MemoryStatus = 'active' | 'archived';
export type MemoryResolvedFrom = 'explicit' | 'default' | 'default_fallback' | 'sediment';
export const DEFAULT_PROJECT_ID = 'default';

export function isDefaultProject(projectId?: string | null): boolean {
  return (projectId ?? '') === DEFAULT_PROJECT_ID;
}
export function isLegacyScope(value: string): boolean {
  return value === 'workspace' || value === 'org';
}

/**
 * 与 apps/admin-web/src/api/memories.ts::MemoryItem 逐字段镜像对齐；全部保持
 * 可选（除 memory_id / scope），避免破坏 MyMemoriesPage.vue 等现有组件。
 */
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
export function memoryErrorText(error: any, fallback = '操作失败'): string {
  const e = normalizeMemoryError(error);
  if (e.notFound) return '内容不存在或你无权查看';
  return e.detail || fallback;
}

export interface MemoryProjectView {
  id: string;
  title: string;
  user_id?: string;
  member_user_ids?: string[];
}
/** project_id + project_owner_id 消歧；查不到 → 「已归档 / 已删除」。 */
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

// ── 分页（T030：与 admin 端统一 page / page_size / total）────────────
/** limit / cursor 作为兼容别名保留（MyMemoriesPage.vue 仍传 limit + cursor）。 */
export interface UserListParams {
  page?: number;
  page_size?: number;
  limit?: number;
  cursor?: string;
  scope?: MemoryScope | '';
  status?: MemoryStatus | '';
  keyword?: string;
}
export interface UserPageResult<T> {
  items: T[];
  next_cursor?: string;
  total?: number;
  page?: number;
  page_size?: number;
}

/** 列表（服务端 visible_to 已过滤；不可见的记忆不会返回）。 */
export async function listMyMemories(params: UserListParams): Promise<UserPageResult<MemoryItem>> {
  const page = params.page ?? 1;
  const page_size = params.page_size ?? params.limit ?? 20;
  const query: Record<string, string | number> = {
    page,
    page_size,
    scope: params.scope ?? '',
    status: params.status ?? '',
    keyword: params.keyword ?? '',
  };
  // cursor 作为「加载更多」的简单偏移透传；不传则不发，避免后端误判偏移。
  if (params.cursor) query.cursor = params.cursor;
  const { data } = await api.get(BASE, { params: query });
  const d = dataOf<any>(data);
  return {
    items: d?.items ?? d?.memories ?? [],
    next_cursor: d?.next_cursor ?? d?.cursor,
    total: d?.total,
    page: d?.page ?? page,
    page_size: d?.page_size ?? page_size,
  };
}

/** 新建：范围由服务端解析，客户端只给「意图」（§7.3 / §9.1）。 */
export interface CreateMemoryPayload {
  content: string;
  scope?: MemoryScope;
  project_id?: string;
  department_id?: string;
  l0_summary?: string;
  l1_overview?: string;
  tierable?: boolean;
  source_session_id?: string;
  source_type?: string;
}
export async function createMemory(payload: CreateMemoryPayload): Promise<MemoryItem> {
  if (payload.scope === 'project' && isDefaultProject(payload.project_id)) {
    throw new Error('default_project_not_shareable');
  }
  const { data } = await api.post(BASE, payload);
  return dataOf<MemoryItem>(data);
}

/** 通用编辑 PATCH /api/v1/memories/{id}（后端已提供）：只改内容类字段，
 *  scope / *_id 等授权字段由服务端解析，客户端传值忽略。 */
export async function updateMemory(id: string, payload: Partial<CreateMemoryPayload>): Promise<MemoryItem> {
  const { data } = await api.patch(`${BASE}/${encodeURIComponent(id)}`, payload);
  return dataOf<MemoryItem>(data);
}

export async function deleteMemory(id: string): Promise<void> {
  await api.delete(`${BASE}/${encodeURIComponent(id)}`);
}

/** 提升 / 提升申请（§9.1 PATCH .../promote）。普通用户由服务端按角色决定直接
 *  提升或落 portal_requests 审批状态机（§7.2 / T035），前端不新建成员端点。 */
export interface PromotePayload {
  target_scope: 'department';
  department_id: string;
  reason?: string;
}
export async function promoteMemory(id: string, payload: PromotePayload): Promise<MemoryItem> {
  // body 为主（后端 MemoryPromotePayload 优先读 body.department_id）；query
  // 双发同一 department_id，兼容只认 query 的旧后端，不会被误回落主部门。
  const { data } = await api.patch(
    `${BASE}/${encodeURIComponent(id)}/promote`,
    payload,
    { params: { department_id: payload.department_id } },
  );
  return dataOf<MemoryItem>(data);
}

/**
 * T035 普通用户「申请提升为部门记忆」：POST /api/v1/memories/{id}/promote/request。
 * 仅记忆 owner 可发起；目标部门须对自身可见。落 pending 队列，由 full_access_admin
 * 在治理端通过 / 驳回。与 promoteMemory 不同——后者是 admin 直接提升（G-1）。
 */
export interface PromoteRequestPayload {
  department_id: string;
  reason?: string;
}
export async function requestPromoteMemory(id: string, payload: PromoteRequestPayload): Promise<MemoryItem> {
  const { data } = await api.post(`${BASE}/${encodeURIComponent(id)}/promote/request`, payload);
  return dataOf<MemoryItem>(data);
}

// ── 049 项目/部门（只读，用于消歧回显与筛选；§9.1）──────────────────
export async function listMemoryProjects(): Promise<MemoryProjectView[]> {
  const { data } = await api.get(PROJECTS_BASE);
  const d = dataOf<any>(data);
  const list = Array.isArray(d) ? d : (d?.items ?? d?.projects ?? []);
  return (Array.isArray(list) ? list : []).map((p: any) => ({
    id: String(p.id ?? p.project_id ?? ''),
    title: String(p.title ?? p.name ?? ''),
    user_id: p.user_id,
    member_user_ids: Array.isArray(p.member_user_ids) ? p.member_user_ids : [],
  }));
}

export interface MemoryDepartmentNode {
  id: string;
  name: string;
  parent_id?: string;
}
export async function listMemoryDepartments(): Promise<MemoryDepartmentNode[]> {
  const { data } = await api.get(`${PROJECTS_BASE}/departments`);
  const d = dataOf<any>(data);
  const list = d?.departments ?? (Array.isArray(d) ? d : []);
  return Array.isArray(list) ? list : [];
}
