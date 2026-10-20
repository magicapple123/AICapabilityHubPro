import { LayoutGrid, List, RefreshCw, Search, X } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { fetchMarketCapabilities, fetchMarketCategories, type MarketCapability } from '@/api/capability'
import { PageHeader } from '@/components/PageHeader'
import { EmptyNote, ErrorNote, Pager } from '@/components/ui'
import { CapabilityCard } from '@/features/market/CapabilityCard'
import { CapabilityDetail } from '@/features/market/CapabilityDetail'
import { fetchExecutors } from '@/features/chat/api'
import { useAsyncResource } from '@/hooks/useAsyncResource'

const SIZE = 12
export function CapabilitiesPage() {
  const [params, setParams] = useSearchParams()
  const [input, setInput] = useState(params.get('q') ?? '')
  const keyword = params.get('q') ?? ''
  const category = Number(params.get('category')) || undefined
  const page = Math.max(1, Number(params.get('page')) || 1)
  const [view, setView] = useState<'grid' | 'list'>('grid')
  const [detail, setDetail] = useState<MarketCapability | null>(null)
  const categories = useAsyncResource(fetchMarketCategories)
  const executors = useAsyncResource(fetchExecutors)
  const load = useCallback(() => fetchMarketCapabilities({
    category_id: category, keyword: keyword || undefined, page, page_size: SIZE,
  }), [category, keyword, page])
  const market = useAsyncResource(load)
  useEffect(() => { setInput(keyword) }, [keyword])
  useEffect(() => {
    if (input.trim() === keyword) return
    const timer = window.setTimeout(() => {
      setParams((previous) => {
        const next = new URLSearchParams(previous)
        if (input.trim()) next.set('q', input.trim()); else next.delete('q')
        next.delete('page')
        return next
      }, { replace: true })
    }, 300)
    return () => window.clearTimeout(timer)
  }, [input, keyword, setParams])
  const changeCategory = (id?: number) => {
    const next = new URLSearchParams(params)
    if (id) next.set('category', String(id)); else next.delete('category')
    next.delete('page')
    setParams(next)
  }
  const reset = () => { setInput(''); setParams({}) }
  return <section className="page">
    <PageHeader title="能力市场" description="选择已上架能力，查看参数和单价后开始调试。"
      actions={<button className="button-secondary" onClick={() => { market.reload(); executors.reload(); categories.reload() }} disabled={market.loading}><RefreshCw size={14} />刷新目录</button>} />

    <div className="market-toolbar"><label className="market-search"><Search size={16} /><input aria-label="搜索能力" placeholder="搜索能力名称、关键词…" value={input} onChange={(e) => setInput(e.target.value)} />
      {input && <button aria-label="清空搜索" onClick={() => setInput('')}><X size={14} /></button>}</label>
      <div className="market-toolbar-right"><span>{market.loading ? '正在查找…' : '共 ' + (market.data?.total ?? 0) + ' 个能力'}</span>
        <div className="view-switch"><button aria-label="卡片视图" aria-pressed={view === 'grid'} onClick={() => setView('grid')}><LayoutGrid size={15} /></button><button aria-label="列表视图" aria-pressed={view === 'list'} onClick={() => setView('list')}><List size={16} /></button></div></div>
    </div>
    <div className="market-categories" aria-label="能力分类"><button aria-pressed={!category} onClick={() => changeCategory()}>全部能力</button>
      {categories.data?.list.map((item) => <button key={item.id} aria-pressed={category === item.id} onClick={() => changeCategory(item.id)}>{item.name}</button>)}
      {categories.error && <button onClick={categories.reload}>分类加载失败 · 重试</button>}
    </div>
    {executors.error && <div className="mb-5"><ErrorNote message="暂时无法确认哪些能力支持执行，请重新加载。" onRetry={executors.reload} /></div>}
    {market.loading ? <div className="market-grid">{[0, 1, 2].map((key) => <div className="panel market-skeleton" key={key} aria-label="正在加载能力"><div className="skeleton h-12 w-12" /><div className="skeleton h-5 w-2/3 mt-6" /><div className="skeleton h-3 w-full mt-4" /><div className="skeleton h-3 w-4/5 mt-2" /><div className="skeleton h-9 w-full mt-10" /></div>)}</div> :
      market.error ? <ErrorNote message={market.error} onRetry={market.reload} /> :
      !market.data?.list.length ? <div className="panel"><EmptyNote message="没有找到符合条件的能力。试试其他关键词，或清除筛选条件。"
        action={<button className="button-secondary" onClick={reset}>清除全部筛选</button>} /></div> :
      <div className={'market-grid' + (view === 'list' ? ' market-list' : '')}>{market.data.list.map((item) => <CapabilityCard key={item.id} item={item} pending={executors.loading}
        supported={!!executors.data?.codes.includes(item.code)} onDetail={() => setDetail(item)} />)}</div>}
    {market.data && market.data.total > SIZE && <div className="mt-5"><Pager page={page} pageSize={SIZE} total={market.data.total} onChange={(value) => { const next = new URLSearchParams(params); next.set('page', String(value)); setParams(next) }} /></div>}
    <p className="market-footnote"><span />仅展示已上架能力。暂未接入执行器的能力会明确标注。</p>
    {detail && <CapabilityDetail key={detail.id} item={detail} supported={!!executors.data?.codes.includes(detail.code)} onClose={() => setDetail(null)} />}
  </section>
}
