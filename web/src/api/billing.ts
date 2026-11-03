import { request } from './client'
import type { PageData } from './types'
import type { GeneratedImage } from './chat'

export interface CallRecordItem {
  id: number
  request_id: string
  user_id: number
  capability_id: number
  service_name: string
  cost: number
  call_status: 'success' | 'degraded' | 'failed'
  duration_ms: number
  model_name: string
  create_time: string
  // C2 / D3：旧记录可能不带这些字段，前端按缺省渲染。
  billing_mode?: 'per_call' | 'per_token' | 'per_unit'
  unit_price?: number | null
  prompt_tokens?: number
  completion_tokens?: number
  units?: number
  /** P6：产生这次调用的 Key；网页调试台与历史记录为 null。 */
  api_key_id?: number | null
  /** P6：入口标记 web / platform_api / openai_compat；历史记录为空串。 */
  entrypoint?: string
  /** D3：文生图的图片产物；非文生图与历史记录为空。 */
  images?: GeneratedImage[]
}

export interface UsageDailyItem {
  stat_date: string
  call_count: number
  total_cost: number
}

export interface ServiceUsageItem {
  service_name: string
  call_count: number
  total_cost: number
}

export interface UsageSummary {
  call_count: number
  total_cost: number
  success_count: number
  degraded_count: number
  failed_count: number
}

/** 个人用量统计（billing-service 契约第 4 节）。 */
export interface UsageData {
  start_date: string
  end_date: string
  summary: UsageSummary
  by_day: UsageDailyItem[]
  by_service: ServiceUsageItem[]
}

export interface TopUserItem {
  user_id: number
  call_count: number
  total_cost: number
}

/** 运营全局统计：summary 额外含去重用户数，并返回消耗排行。 */
export interface OverviewData extends Omit<UsageData, 'summary'> {
  summary: UsageSummary & { user_count: number }
  top_users: TopUserItem[]
}

export interface DateRangeQuery {
  start_date?: string
  end_date?: string
}

export interface CallRecordQuery extends DateRangeQuery {
  service_name?: string
  call_status?: 'success' | 'degraded' | 'failed'
  page?: number
  page_size?: number
}

export const fetchCallRecords = (params: CallRecordQuery = {}) =>
  request<PageData<CallRecordItem>>({ method: 'GET', url: '/billing/records', params })

export const fetchUsage = (params: DateRangeQuery = {}) =>
  request<UsageData>({ method: 'GET', url: '/billing/usage', params })

export const fetchOverview = (params: DateRangeQuery = {}) =>
  request<OverviewData>({ method: 'GET', url: '/billing/stat/overview', params })

/* ------------------------------------------------------------------ */
/* F1 管理端跨用户查询（需管理员，普通用户 2007）                       */
/* ------------------------------------------------------------------ */

export interface AdminCallRecordQuery extends CallRecordQuery {
  user_id: number
  /** P6：按 Key 归因筛选；不传表示该用户全部记录。 */
  api_key_id?: number
}

/** 管理端调用明细：按目标用户过滤，统计口径与个人接口一致。 */
export const fetchAdminCallRecords = (params: AdminCallRecordQuery) =>
  request<PageData<CallRecordItem>>({ method: 'GET', url: '/billing/admin/records', params })

/** 管理端指定用户用量（缺省近 30 天）：汇总 + 按天 + 按服务。 */
export const fetchAdminUserUsage = (userId: number, params: DateRangeQuery = {}) =>
  request<UsageData>({ method: 'GET', url: `/billing/admin/users/${userId}/usage`, params })

/* ------------------------------------------------------------------ */
/* P5 / P6 管理端聚合（需管理员，普通用户 2007）                        */
/* ------------------------------------------------------------------ */

/** 全量用户的用量聚合；只含统计区间内有过调用的用户。 */
export interface UserUsageAggregate {
  user_id: number
  call_count: number
  total_cost: number
  last_call_at: string | null
}

export interface UserUsageAggregateData {
  start_date: string
  end_date: string
  list: UserUsageAggregate[]
}

/** 单个用户按 Key 的用量；Key 名称由 user-service 的 Key 列表补齐。 */
export interface KeyUsageAggregate {
  api_key_id: number
  call_count: number
  total_cost: number
  last_call_at: string | null
}

export interface KeyUsageData {
  user_id: number
  start_date: string
  end_date: string
  list: KeyUsageAggregate[]
}

/**
 * 全量用户消耗聚合（P5）：一次返回统计区间内所有有调用的用户，
 * 由前端与 `/api/user/admin/users?page_size=2000` 按 user_id join 后排序分页。
 * 这里**不分页**是刻意的：用户资料在 user-service、消耗在 billing_db，
 * 服务端排序等于跨服务 join，见 UserUsagePanel 里的 2000 上限说明。
 */
export const fetchAdminUserAggregates = (params: DateRangeQuery = {}) =>
  request<UserUsageAggregateData>({ method: 'GET', url: '/billing/admin/users/usage', params })

/** 指定用户按 API Key 的调用分布（P6）；只返回 Key ID 与用量，不含任何密钥材料。 */
export const fetchAdminUserKeyUsage = (userId: number, params: DateRangeQuery = {}) =>
  request<KeyUsageData>({ method: 'GET', url: `/billing/admin/users/${userId}/keys-usage`, params })
