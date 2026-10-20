import { ArrowDownLeft, ArrowUpRight, Coins, LockKeyhole } from 'lucide-react'
import { useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import { fetchPoints, fetchPointsLogs } from '@/api/user'
import { StatCard } from '@/components/StatCard'
import { EmptyNote, ErrorNote, Loading, Pager } from '@/components/ui'
import { CopyButton } from '@/components/CopyButton'
import { useAsyncResource } from '@/hooks/useAsyncResource'
import { formatNumber } from '@/lib/dateRange'

const SIZE = 8
export function PointsSettings() {
  const [params, setParams] = useSearchParams()
  const direction = params.get('direction') === 'in' ? 'in' : params.get('direction') === 'out' ? 'out' : ''
  const page = Math.max(1, Number(params.get('page')) || 1)
  const load = useCallback(async () => {
    const [account, logs] = await Promise.all([fetchPoints(), fetchPointsLogs({ direction: direction || undefined, page, page_size: SIZE })])
    return { account, logs }
  }, [direction, page])
  const resource = useAsyncResource(load)
  const update = (key: string, value: string) => {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value); else next.delete(key)
    if (key !== 'page') next.delete('page')
    setParams(next)
  }
  return <div>{resource.error && <div className="mb-5"><ErrorNote message={resource.error} onRetry={resource.reload} /></div>}
    <div className="points-stats">
      <StatCard title="当前可用积分" value={formatNumber(resource.data?.account.balance)} detail="用于能力调用的可用余额" icon={<Coins size={19} />} accent loading={!resource.data && resource.loading} />
      <StatCard title="冻结积分" value={formatNumber(resource.data?.account.frozen)} detail="以积分账户实时返回为准" icon={<LockKeyhole size={19} />} loading={!resource.data && resource.loading} />
      <div className="points-tip"><h3>积分说明</h3><p>调用按能力目录单价计量。模型故障降级不扣费，实际扣费可在调用明细中核对。</p></div>
    </div>
    <section className="panel"><div className="panel-head"><div><h2>积分明细</h2><p>追踪积分的每一笔收支</p></div><div className="segmented">{[
      { value: '', label: '全部收支' }, { value: 'in', label: '积分入账' }, { value: 'out', label: '积分支出' },
    ].map((item) => <button key={item.value} aria-pressed={item.value === direction} onClick={() => update('direction', item.value)}>{item.label}</button>)}</div></div>
      {resource.loading ? <Loading label="正在加载积分明细…" /> : !resource.data?.logs.list.length ? <EmptyNote message="当前筛选下没有积分明细。" /> :
        <div className="points-log-list">{resource.data.logs.list.map((item) => <div key={item.id} className="points-log">
          <span className={'points-direction ' + (item.direction === 'in' ? 'income' : '')}>{item.direction === 'in' ? <ArrowDownLeft size={18} /> : <ArrowUpRight size={18} />}</span>
          <span className="points-log-description"><strong>{item.remark || (item.biz_type === 'register' ? '注册赠送积分' : '能力调用')}</strong><small>{item.create_time}</small>
            {item.request_id && <span className="points-request"><code>{item.request_id}</code><CopyButton text={item.request_id} label="复制 requestId" compact /></span>}</span>
          <span className={'points-amount ' + (item.direction === 'in' ? 'income' : '')}>{item.direction === 'in' ? '+' : '-'}{item.amount}</span><span className="points-after">余额 {item.balance_after}</span>
        </div>)}</div>}
      <Pager page={page} pageSize={SIZE} total={resource.data?.logs.total ?? 0} onChange={(value) => update('page', String(value))} />
    </section></div>
}
