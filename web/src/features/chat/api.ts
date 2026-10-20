import { request } from '@/api/client'
import { displayText } from '@/lib/displayText'
import type { ExecutorCatalog, MarketDetail } from './types'

export const fetchMarketDetail = (id: number) =>
  request<MarketDetail>({ method: 'GET', url: '/capability/market/' + id }).then((item) => ({
    ...item, name: displayText(item.name), description: displayText(item.description), category_name: displayText(item.category_name),
  }))
export const fetchExecutors = () => request<ExecutorCatalog>({ method: 'GET', url: '/chat/executors' })
