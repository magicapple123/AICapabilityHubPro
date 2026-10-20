import { request } from './client'
import { displayText, legacySearchText } from '@/lib/displayText'

/** 与 docs/api-contract/capability-service.md 第 4 节的市场出参一一对应。 */
export interface MarketCapability {
  id: number
  name: string
  code: string
  category_id: number
  category_name: string
  description: string
  price_per_call: number
  update_time: string
}

export interface MarketCategory {
  id: number
  name: string
  code: string
}

export interface PageData<T> {
  list: T[]
  total: number
  page: number
  page_size: number
}

export interface ListData<T> {
  list: T[]
  total: number
}

export interface MarketQuery {
  category_id?: number
  keyword?: string
  page?: number
  page_size?: number
}

/**
 * 能力市场列表（网关白名单，无需登录）。
 *
 * 路径只写网关路由之后的剩余部分：apiClient 的 baseURL 已经是 /api，
 * 写成 '/api/capability/market' 会被拼成 /api/api/capability/market 而 404。
 */
export const fetchMarketCapabilities = async (params: MarketQuery = {}) => {
  const fetch = (query: MarketQuery) => request<PageData<MarketCapability>>({ method: 'GET', url: '/capability/market', params: query })
  let page = await fetch(params)
  // A fallback search accommodates existing demo rows with the legacy encoding.
  const fallback = params.keyword ? legacySearchText(params.keyword) : ''
  if (params.keyword && !page.total && fallback !== params.keyword) page = await fetch({ ...params, keyword: fallback })
  return { ...page, list: page.list.map((item) => ({
    ...item, name: displayText(item.name), category_name: displayText(item.category_name), description: displayText(item.description),
  })) }
}

/** 市场筛选栏分类，只返回存在已上架能力的分类。 */
export const fetchMarketCategories = () =>
  request<ListData<MarketCategory>>({ method: 'GET', url: '/capability/market/categories' }).then((data) => ({ ...data, list: data.list.map((item) => ({ ...item, name: displayText(item.name) })) }))

/* ------------------------------------------------------------------ */
/* 运营侧接口（均需要登录，契约第 2、3、4 节）                          */
/* ------------------------------------------------------------------ */

export type CapabilityStatus = 'draft' | 'online' | 'offline'
export type CategoryStatus = 'enabled' | 'disabled'

/** 分类对象（运营）；时间格式 YYYY-MM-DD HH:MM:SS。 */
export interface CategoryItem {
  id: number
  name: string
  code: string
  sort: number
  status: CategoryStatus
  create_time: string
  update_time: string
}

/** 运营列表项：比市场多 service_name / path / param_schema / status。 */
export interface CapabilityManageItem {
  id: number
  category_id: number
  category_name: string
  name: string
  code: string
  service_name: string
  path: string
  param_schema: Record<string, unknown> | null
  price_per_call: number
  status: CapabilityStatus
  description: string
  create_time: string
  update_time: string
}

export interface CategoryCreatePayload {
  name: string
  code: string
  sort?: number
}

/** 字段均可选，仅提交需要变更的项。 */
export interface CategoryUpdatePayload {
  name?: string
  code?: string
  sort?: number
  status?: CategoryStatus
}

export interface CapabilityCreatePayload {
  category_id: number
  name: string
  code: string
  service_name: string
  path: string
  param_schema?: Record<string, unknown> | null
  price_per_call?: number
  status?: CapabilityStatus
  description?: string
}

/** 编辑能力；状态变更必须走 updateCapabilityStatus。 */
export interface CapabilityUpdatePayload {
  category_id?: number
  name?: string
  code?: string
  service_name?: string
  path?: string
  param_schema?: Record<string, unknown> | null
  price_per_call?: number
  description?: string
}

export interface CategoryQuery {
  status?: CategoryStatus
  keyword?: string
}

export interface ManageCapabilityQuery {
  status?: CapabilityStatus
  category_id?: number
  keyword?: string
  page?: number
  page_size?: number
}

export const fetchCategories = (params: CategoryQuery = {}) =>
  request<ListData<CategoryItem>>({ method: 'GET', url: '/capability/categories', params }).then((data) => ({ ...data, list: data.list.map((item) => ({ ...item, name: displayText(item.name) })) }))

export const createCategory = (data: CategoryCreatePayload) =>
  request<CategoryItem>({ method: 'POST', url: '/capability/categories', data })

export const updateCategory = (categoryId: number, data: CategoryUpdatePayload) =>
  request<CategoryItem>({ method: 'PUT', url: `/capability/categories/${categoryId}`, data })

export const deleteCategory = (categoryId: number) =>
  request<{ id: number; is_deleted: number }>({
    method: 'DELETE',
    url: `/capability/categories/${categoryId}`,
  })

export const fetchManageCapabilities = (params: ManageCapabilityQuery = {}) =>
  request<PageData<CapabilityManageItem>>({ method: 'GET', url: '/capability/manage', params }).then((data) => ({ ...data, list: data.list.map((item) => ({ ...item, name: displayText(item.name), category_name: displayText(item.category_name), description: displayText(item.description) })) }))

export const createCapability = (data: CapabilityCreatePayload) =>
  request<CapabilityManageItem>({ method: 'POST', url: '/capability', data })

export const updateCapability = (capabilityId: number, data: CapabilityUpdatePayload) =>
  request<CapabilityManageItem>({ method: 'PUT', url: `/capability/${capabilityId}`, data })

export const deleteCapability = (capabilityId: number) =>
  request<{ id: number; is_deleted: number }>({
    method: 'DELETE',
    url: `/capability/${capabilityId}`,
  })

export const updateCapabilityStatus = (capabilityId: number, status: CapabilityStatus) =>
  request<{ id: number; status: string; update_time: string }>({
    method: 'PUT',
    url: `/capability/${capabilityId}/status`,
    data: { status },
  })
