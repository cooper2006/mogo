/**
 * 051 数字员工 —— 终端用户侧 API 客户端。
 *
 * 走 chat-api ``/askai-api`` 前缀（``end_user`` 会话，Authorization 由
 * ``createApiClient`` 统一注入）；租户由会话决定，前端不传 tenantId。
 *
 * 后端契约见 ``services/chat-api/app/api/endpoints/employees.py``。
 */
import { createApiClient } from './client'

const api = createApiClient({ baseURL: '/askai-api/api', timeout: 30000 })

export interface EmployeeCapabilities {
  content_generation: boolean
  image_generation: boolean
  code_generation: boolean
  browser_automation: boolean
  internal_knowledge: boolean
}

/** 051 FR-003 / FR-005：终端用户侧员工条目（available 仅 active 且未软删）。 */
export interface PortalEmployeeItem {
  id: string
  name: string
  description: string
  status: 'active' | 'disabled' | 'archived'
  capabilities: EmployeeCapabilities
  available: boolean
}

export interface PortalEmployeePage {
  items: PortalEmployeeItem[]
  total: number
}

/** 可用员工列表（仅 active 且当前用户可见）。 */
export async function fetchPortalEmployees(): Promise<PortalEmployeePage> {
  const { data } = await api.get('/employees')
  return data as PortalEmployeePage
}
