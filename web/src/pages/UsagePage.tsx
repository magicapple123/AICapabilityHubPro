import { Activity, CheckCheck, Coins, Download, RefreshCw, Zap } from 'lucide-react'
import { useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import { fetchCallRecords, fetchUsage } from '@/api/billing'
import { fetchPoints } from '@/api/user'
import { PageHeader } from '@/components/PageHeader'
import { StatCard } from '@/components/StatCard'
import { ErrorNote, Loading, Pager } from '@/components/ui'
import { RecordTable } from '@/features/usage/RecordTable'
import { UsageChart } from '@/features/usage/UsageChart'
import { exportRecords } from '@/features/usage/exportRecords'
import { useAsyncResource } from '@/hooks/useAsyncResource'
import { dateRange, formatNumber } from '@/lib/dateRange'

const STATUSES = [
  { value: '', label: '全部状态' }, { value: 'success', label: '成功' },
  { value: 'degraded', label: '降级' }, { value: 'failed', label: '失败' },
] as const
const SIZE = 10
export function UsagePage() {
  const [params, setParams] = useSearchParams()
  const days = params.get('range') === '7' ? 7 : params.get('range') === '90' ? 90 : 30
  const rawStatus = params.get('status')
  const status = STATUSES.find((item) => item.value === rawStatus)?.value ?? ''
  const page = Math.max(1, Number(params.get('page')) || 1)
  const load = useCallback(async () => {
    const range = dateRange(days)
    const [points, usage, records] = await Promise.all([
      fetchPoints(), fetchUsage(range),
      fetchCallRecords({ ...range, call_status: status || undefined, page, page_size: SIZE }),
    ])
    return { points, usage, records }
  }, [days, status, page])
  const resource = useAsyncResource(load)
  const data = resource.data
  const summary = data?.usage.summary
  const update = (key: string, value: string) => {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value); else next.delete(key)
    if (key !== 'page') next.delete('page')
    setParams(next)
  }
  return <section className="page" aria-busy={resource.loading}>
    <PageHeader title="调用记录" description="查看个人用量，按日期和执行状态查询调用明细。"
      actions={<><button className="button-secondary" aria-label="刷新用量" onClick={resource.reload} disabled={resource.loading}><RefreshCw size={14} />刷新</button>
        <button className="button-primary" disabled={resource.loading || !!resource.error || !data?.records.list.length} onClick={() => data && exportRecords(data.records.list)}><Download size={14} />导出当前页</button></>} />
    <div className="usage-range"><span className="muted">统计区间</span><div className="segmented">{[7, 30, 90].map((day) =>
      <button key={day} aria-pressed={days === day} onClick={() => update('range', String(day))}>近 {day} 天</button>)}</div>
      <span className="usage-range-date">{dateRange(days).start_date} — {dateRange(days).end_date}</span></div>
    {resource.error && <div className="mb-5"><ErrorNote message={resource.error} onRetry={resource.reload} /></div>}
    <div className="stats-grid">
      <StatCard title="可用积分" value={formatNumber(data?.points.balance)} detail="积分余额实时查询" icon={<Coins size={17} />} accent loading={!data && resource.loading} />
      <StatCard title="区间调用次数" value={formatNumber(summary?.call_count)} detail={'近 ' + days + ' 天累计调用'} icon={<Activity size={17} />} loading={!data && resource.loading} />
      <StatCard title="区间消耗积分" value={formatNumber(summary?.total_cost)} detail="降级执行不收取积分" icon={<Zap size={17} />} loading={!data && resource.loading} />
      <StatCard title="调用成功率" value={summary?.call_count ? (summary.success_count / summary.call_count * 100).toFixed(1) + '%' : '—'} detail={summary ? '降级 ' + summary.degraded_count + ' 次 · 失败 ' + summary.failed_count + ' 次' : '暂无统计结果'} icon={<CheckCheck size={17} />} loading={!data && resource.loading} />
    </div>
    <div className="usage-visuals"><section className="panel"><div className="panel-head"><div><h2>每日调用趋势</h2><p>查看区间内的调用次数与积分消耗</p></div><span className="period-label">近 {days} 天</span></div>
      <div className="panel-body">{data ? <UsageChart usage={data.usage} /> : <Loading />}</div></section>
      <section className="panel"><div className="panel-head"><div><h2>服务使用分布</h2><p>按调用次数排序</p></div></div>
        <div className="service-distribution">{data?.usage.by_service.length ? [...data.usage.by_service].sort((a, b) => b.call_count - a.call_count).map((item) =>
          <div key={item.service_name}><p><strong>{item.service_name || '未标注服务'}</strong><span>{item.call_count} 次</span></p><div className="distribution-track"><i style={{ width: (item.call_count / Math.max(1, summary?.call_count ?? 1) * 100) + '%' }} /></div><small>消耗 {item.total_cost} 积分</small></div>) :
          <p className="distribution-empty">完成调用后即可查看服务分布</p>}</div></section></div>
    <section className="panel"><div className="panel-head records-header"><div><h2>调用明细</h2><p>点击行末箭头，查看费用、耗时和完整追踪编号</p></div>
      <div className="segmented" aria-label="调用状态筛选">{STATUSES.map((item) => <button key={item.value} aria-pressed={status === item.value} onClick={() => update('status', item.value)}>{item.label}</button>)}</div></div>
      {resource.loading ? <Loading label="正在查询调用记录…" /> : resource.error ? <div className="panel-body"><ErrorNote message={resource.error} onRetry={resource.reload} /></div> : <RecordTable records={data?.records.list ?? []} />}
      <Pager page={page} pageSize={SIZE} total={data?.records.total ?? 0} onChange={(value) => update('page', String(value))} />
    </section>
  </section>
}
