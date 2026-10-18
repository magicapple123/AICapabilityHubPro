import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { fetchMarketCapabilities } from '@/api/capability'
import type { MarketCapability } from '@/api/capability'
import { fetchExecutors, fetchMarketDetail } from './api'
import { positiveCapabilityId } from './schemaInput'
import type { ExecutorCatalog, MarketDetail } from './types'

export function useCapabilityCatalog() {
  const [params, setParams] = useSearchParams()
  const rawId = params.get('capability_id') ?? params.get('capabilityId') ?? '1'
  const id = positiveCapabilityId(rawId)
  const [list, setList] = useState<MarketCapability[]>([])
  const [detail, setDetail] = useState<MarketDetail | null>(null)
  const [executors, setExecutors] = useState<ExecutorCatalog | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)

  useEffect(() => {
    let ignore = false
    setLoading(true)
    setError('')
    setDetail(null)
    const load = async () => {
      try {
        const [market, adapters] = await Promise.all([
          fetchMarketCapabilities({ page: 1, page_size: 100 }), fetchExecutors(),
        ])
        if (ignore) return
        setList(market.list)
        setExecutors(adapters)
        if (id === null) throw new Error('能力 ID 无效，请从列表中重新选择。')
        const selected = await fetchMarketDetail(id)
        if (!ignore) setDetail(selected)
      } catch (cause) {
        if (!ignore) setError(cause instanceof Error ? cause.message : '能力加载失败。')
      } finally {
        if (!ignore) setLoading(false)
      }
    }
    void load()
    return () => { ignore = true }
  }, [id, retry])

  const select = (nextId: string) => {
    const next = new URLSearchParams(params)
    next.delete('capabilityId')
    next.set('capability_id', nextId)
    setParams(next)
  }
  return { id, list, detail, executors, loading, error, select, retry: () => setRetry((n) => n + 1) }
}
