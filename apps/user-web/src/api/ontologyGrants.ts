import { createApiClient } from './client'

/**
 * 本体数据权限 —— 终端用户侧（030 迁移）。
 *
 * 对应 chat-api `services/chat-api/app/api/endpoints/ontology_grants.py`
 * （prefix `/api/ontology-grants`）。本模块**只读**：授权由管理端在 admin-web
 * 「本体清单」页维护，用户侧只查看「我」被授予了哪些本体。
 */

const api = createApiClient({ baseURL: '/askai-api/api', timeout: 30000 })
const dataOf = <T>(res: { data?: any }): T => res.data?.data ?? res.data

export type OntologyAccessMode = 'none' | 'read' | 'write'

export interface MyOntologyGrant {
  /** 本体标识（ontology_id）。 */
  ontologyId: string
  /** 生效的访问模式（tenant 兜底与用户自身授权合并后的结果）。 */
  accessMode: OntologyAccessMode
  priority: number
  /** 该行来自哪个主体：tenant 兜底或 user 自身。 */
  subjectType: 'tenant' | 'user'
  remark: string
  updatedAt: string | null
  /** accessMode ∈ {read, write} 即可见。 */
  visible: boolean
}

export interface MyOntologyScope {
  tenantId: string
  userId: string
  ontologies: MyOntologyGrant[]
  count: number
  /** 其中可见（accessMode ≠ none）的条数。 */
  visibleCount: number
  /** 已停用（enabled=false）的授权行数；>0 表示有"配了却没生效"的授权。 */
  disabledCount: number
  /** true = 查询后端失败，本次展示为空（不阻断其它功能）。 */
  degraded: boolean
}

/** 当前登录用户的本体授权（tenant 兜底 + 用户自身，已按优先级合并）。 */
export async function fetchMyOntologyGrants(): Promise<MyOntologyScope> {
  return dataOf<MyOntologyScope>(await api.get('/ontology-grants/mine'))
}
