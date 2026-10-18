import { request } from '@/api/client'
import type { ExecutorCatalog, MarketDetail } from './types'

export const fetchMarketDetail = (id: number) =>
  request<MarketDetail>({ method: 'GET', url: `/capability/market/${id}` })

export const fetchExecutors = () =>
  request<ExecutorCatalog>({ method: 'GET', url: '/chat/executors' })
