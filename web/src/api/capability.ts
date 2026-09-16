import { request } from './client'

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
export const fetchMarketCapabilities = (params: MarketQuery = {}) =>
  request<PageData<MarketCapability>>({ method: 'GET', url: '/capability/market', params })

/** 市场筛选栏分类，只返回存在已上架能力的分类。 */
export const fetchMarketCategories = () =>
  request<ListData<MarketCategory>>({ method: 'GET', url: '/capability/market/categories' })
