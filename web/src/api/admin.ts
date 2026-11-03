import { apiClient, request } from './client'
import type { PageData } from './capability'
import type { UsageData } from './billing'

/** 与 docs/api-contract/user-service.md 第 9 节（F1）一致。 */
export interface AdminUser {
  id: number
  username: string
  nickname: string
  role: string
  status: 'normal' | 'disabled'
  balance: number
  daily_points_limit: number
  create_time: string
}

/** 详情抽屉里的 Key 元数据；服务端不下发 secret / secret_hash。 */
export interface AdminApiKeyItem {
  id: number
  name: string
  access_key: string
  status: string
  create_time: string
}

/** 用户详情：`usage` 复用 billing 统计口径，对端不可用时为 null。 */
export interface AdminUserDetail extends AdminUser {
  today_used: number
  usage: UsageData | null
  api_keys: AdminApiKeyItem[]
}

export interface AdminUserQuery {
  keyword?: string
  status?: 'normal' | 'disabled'
  page?: number
  page_size?: number
}

export const fetchAdminUsers = (params: AdminUserQuery = {}) =>
  request<PageData<AdminUser>>({ method: 'GET', url: '/user/admin/users', params })

export const fetchAdminUser = (id: number) =>
  request<AdminUserDetail>({ method: 'GET', url: `/user/admin/users/${id}` })

export const setAdminUserStatus = (id: number, status: 'normal' | 'disabled') =>
  request<{ id: number; status: string }>({
    method: 'PUT', url: `/user/admin/users/${id}/status`, data: { status },
  })

export const adjustAdminUserPoints = (id: number, amount: number, reason: string) =>
  request<{ id: number; balance: number; amount: number }>({
    method: 'POST', url: `/user/admin/users/${id}/points`, data: { amount, reason },
  })

/** 日预算（P10）：0 = 不限，上限与单次调分同量级；后端写 `resource_type=user, action=budget` 审计。 */
export const setAdminUserBudget = (id: number, dailyPointsLimit: number) =>
  request<{ id: number; daily_points_limit: number }>({
    method: 'PUT', url: `/user/admin/users/${id}/budget`,
    data: { daily_points_limit: dailyPointsLimit },
  })

/**
 * 导出 CSV：必须走带 Authorization 的请求，不能简单地用 <a href> 打开
 * （那样浏览器不会带 Token，会被网关判 401）。下载用 Blob URL 触发。
 */
export const downloadAdminUsers = async (params: AdminUserQuery = {}) => {
  const response = await apiClient.request<Blob>({
    method: 'GET', url: '/user/admin/users/export', params, responseType: 'blob',
  })
  const url = URL.createObjectURL(response.data)
  const link = document.createElement('a')
  link.href = url
  link.download = 'users.csv'
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}
