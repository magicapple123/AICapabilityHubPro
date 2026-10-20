import { Activity, Coins, Layers3, Users } from 'lucide-react'
import { fetchOverview } from '@/api/billing'
import { StatCard } from '@/components/StatCard'
import { EmptyNote, ErrorNote, Loading } from '@/components/ui'
import { useAsyncResource } from '@/hooks/useAsyncResource'
import { dateRange, formatNumber } from '@/lib/dateRange'
import { useCallback } from 'react'
import { UsageChart } from '@/features/usage/UsageChart'

export function PlatformUsage() {
  const load = useCallback(() => fetchOverview(dateRange(30)), [])
  const overview = useAsyncResource(load)
  if (overview.loading && !overview.data) return <div className="panel"><Loading label="正在读取平台用量…" /></div>
  if (overview.error) return <ErrorNote message={overview.error} onRetry={overview.reload} />
  if (!overview.data) return null
  const data = overview.data
  return <><div className="stats-grid">
    <StatCard title="平台调用" value={formatNumber(data.summary.call_count)} detail="近 30 天累计" icon={<Activity size={17} />} accent />
    <StatCard title="消耗积分" value={formatNumber(data.summary.total_cost)} detail="近 30 天实际消耗" icon={<Coins size={17} />} />
    <StatCard title="调用用户" value={formatNumber(data.summary.user_count)} detail="统计区间内去重用户" icon={<Users size={17} />} />
    <StatCard title="调用服务" value={data.by_service.length} detail="有调用记录的服务数量" icon={<Layers3 size={17} />} />
  </div><div className="usage-visuals"><div className="panel"><div className="panel-head"><h2>平台调用趋势</h2><span className="period-label">近 30 天</span></div><div className="panel-body"><UsageChart usage={data} /></div></div>
    <div className="panel"><div className="panel-head"><h2>积分消耗排行</h2><span className="muted text-xs">Top 10</span></div>
      {data.top_users.length ? <div className="ranking-list">{data.top_users.map((item, index) => <div key={item.user_id}><span>{String(index + 1).padStart(2, '0')}</span><strong>用户 #{item.user_id}</strong><small>{item.call_count} 次</small><b>{item.total_cost} 积分</b></div>)}</div> : <EmptyNote message="统计区间内没有调用用户。" />}</div></div></>
}
