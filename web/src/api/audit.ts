import { request } from './client'
import type { PageData } from './capability'

/** 与 docs/api-contract/capability-service.md 第 9 节（审计）一一对应。 */
export interface AuditLog {
  id: number
  operator_id: string
  operator_name: string
  resource_type: string
  resource_id: string
  action: string
  before_json: Record<string, unknown> | null
  after_json: Record<string, unknown> | null
  request_id: string
  create_time: string
}

export interface AuditQuery {
  resource_type?: string
  resource_id?: string
  action?: string
  operator_id?: string
  start_date?: string
  end_date?: string
  page?: number
  page_size?: number
}

export const fetchAuditLogs = (params: AuditQuery = {}) =>
  request<PageData<AuditLog>>({ method: 'GET', url: '/capability/audit', params })
