import { request } from './client'
import type { ListData, PageData } from './types'

/** 用户资料；出参不含 password_hash（user-service 契约第 2 节）。 */
export interface Profile {
  user_id: number
  username: string
  nickname: string
  status: string
  create_time: string
  update_time: string
}

/** 本期只允许修改昵称。 */
export interface ProfileUpdatePayload {
  nickname: string
}

export interface ApiKeyItem {
  id: number
  name: string
  access_key: string
  secret_mask: string
  status: string
  expire_time: string | null
  create_time: string
}

/** 创建响应额外返回一次 `secret_key`，库内只存摘要，之后无法再取回。 */
export interface ApiKeyCreated extends ApiKeyItem {
  secret_key: string
}

export interface ApiKeyCreatePayload {
  name?: string
  /** 为空表示永不过期，格式 YYYY-MM-DD HH:MM:SS。 */
  expire_time?: string
}

export interface PointsAccount {
  user_id: number
  balance: number
  frozen: number
}

export interface PointsLogItem {
  id: number
  direction: 'in' | 'out'
  amount: number
  balance_after: number
  biz_type: string
  request_id: string
  remark: string
  create_time: string
}

export interface PointsLogQuery {
  direction?: 'in' | 'out'
  page?: number
  page_size?: number
}

export const fetchProfile = () => request<Profile>({ method: 'GET', url: '/user/profile' })

export const updateProfile = (data: ProfileUpdatePayload) =>
  request<Profile>({ method: 'PUT', url: '/user/profile', data })

export const fetchApiKeys = () =>
  request<ListData<ApiKeyItem>>({ method: 'GET', url: '/user/apikeys' })

export const createApiKey = (data: ApiKeyCreatePayload) =>
  request<ApiKeyCreated>({ method: 'POST', url: '/user/apikeys', data })

export const disableApiKey = (apiKeyId: number) =>
  request<{ id: number; status: string; update_time: string }>({
    method: 'PUT',
    url: `/user/apikeys/${apiKeyId}/disable`,
  })

export const fetchPoints = () =>
  request<PointsAccount>({ method: 'GET', url: '/user/points' })

export const fetchPointsLogs = (params: PointsLogQuery = {}) =>
  request<PageData<PointsLogItem>>({ method: 'GET', url: '/user/points/logs', params })
