import { ArrowRight, ArrowUpRight, CalendarDays, RefreshCw } from 'lucide-react'
import { useCallback } from 'react'
import { Link } from 'react-router-dom'
import { fetchCallRecords, fetchUsage } from '@/api/billing'
import { fetchMarketCapabilities } from '@/api/capability'
import { fetchPoints } from '@/api/user'
import { PageHeader } from '@/components/PageHeader'
import { StatCard } from '@/components/StatCard'
import { ErrorNote, Loading } from '@/components/ui'
import { useAsyncResource } from '@/hooks/useAsyncResource'
import { dateRange, formatNumber } from '@/lib/dateRange'
import { RecordTable } from '@/features/usage/RecordTable'
import { UsageChart } from '@/features/usage/UsageChart'

export function OverviewPage() {
  const load = useCallback(async () => {
    const [usage, points, market, records] = await Promise.all([
      fetchUsage(dateRange(7)), fetchPoints(), fetchMarketCapabilities({ page: 1, page_size: 100 }),
      fetchCallRecords({ page: 1, page_size: 4 }),
    ])
    return { usage, points, market, records }
  }, [])
  const resource = useAsyncResource(load)
  const data = resource.data
  const summary = data?.usage.summary
  const success = summary && summary.call_count > 0 ? (summary.success_count / summary.call_count * 100).toFixed(1) + '%' : '—'
  const chat = data?.market.list.find((item) => item.code === 'chat-completions')
  const text = data?.market.list.find((item) => item.code === 'long-summary')
  return <section className="page overview-page">
    <PageHeader title="工作台" description="个人账户与最近 7 天的使用情况。"
      actions={<><span className="date-label"><CalendarDays size={14} />{new Date().toLocaleDateString('zh-CN', { month: 'long', day: 'numeric', weekday: 'long' })}</span>
        <button className="icon-button" aria-label="刷新工作台" disabled={resource.loading} onClick={resource.reload}><RefreshCw size={16} className={resource.loading ? 'spinner' : ''} /></button></>} />
    {resource.error && <div className="mb-5"><ErrorNote message={resource.error} onRetry={resource.reload} /></div>}
    <div className="stats-grid overview-stats">
      <StatCard title="可用积分" value={formatNumber(data?.points.balance)} detail={<Link to="/settings?tab=points" className="stat-link">积分明细 <ArrowUpRight size={11} /></Link>} loading={resource.loading && !data} />
      <StatCard title="近 7 天调用" value={formatNumber(summary?.call_count)} detail="累计调用次数" loading={resource.loading && !data} />
      <StatCard title="消耗积分" value={formatNumber(summary?.total_cost)} detail="近 7 天实际扣费" loading={resource.loading && !data} />
      <StatCard title="成功率" value={success} detail={summary?.call_count ? '降级 ' + summary.degraded_count + ' 次 · 失败 ' + summary.failed_count + ' 次' : '暂无调用'} loading={resource.loading && !data} />
    </div>
    <div className="dashboard-middle">
      <section className="panel"><div className="panel-head"><div><h2>调用趋势</h2><p>每日调用次数</p></div><span className="period-label">最近 7 天</span></div>
        <div className="panel-body">{data ? <UsageChart usage={data.usage} /> : <Loading label={resource.error ? '等待重新加载' : '正在读取用量…'} />}</div></section>
      <section className="panel quick-panel"><div className="panel-head"><h2>常用操作</h2></div>
        <div className="quick-list">
          <Link to={chat ? '/chat?capability_id=' + chat.id : '/capabilities'} className="quick-item"><span className="quick-number">01</span><span><strong>新建对话</strong><small>选择聊天能力，开始调试</small></span><ArrowUpRight size={15} /></Link>
          <Link to={text ? '/chat?capability_id=' + text.id : '/capabilities'} className="quick-item"><span className="quick-number">02</span><span><strong>文本摘要</strong><small>粘贴文本并设置摘要要求</small></span><ArrowUpRight size={15} /></Link>
          <Link to="/settings?tab=keys" className="quick-item"><span className="quick-number">03</span><span><strong>API Key</strong><small>查看和管理访问凭证</small></span><ArrowUpRight size={15} /></Link>
        </div><Link className="quick-directory" to="/capabilities">查看能力目录<ArrowRight size={13} /></Link>
      </section>
    </div>
    <section className="panel recent-panel"><div className="panel-head"><div><h2>最近调用</h2><p>最近 4 条执行记录</p></div><Link className="text-link" to="/usage">全部记录<ArrowRight size={13} /></Link></div>
      {data ? <RecordTable records={data.records.list} compact /> : <Loading label="正在读取最近调用…" />}
    </section>
  </section>
}
