import { request } from './client'
import type { PageData } from './types'

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
