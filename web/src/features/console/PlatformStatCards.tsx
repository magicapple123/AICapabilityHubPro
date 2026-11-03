import type { OverviewData } from '@/api/billing'
import { StatCard } from '@/components/StatCard'
import { formatNumber } from '@/lib/dateRange'

/**
 * 平台级四张统计卡（P5）：从「平台用量」页抽出的可复用组件，
 * 数据只来自 billing 的 `/stat/overview`，不掺 user-service 的口径。
 */
export function PlatformStatCards({ overview, days }: { overview: OverviewData; days: number }) {
  const period = `近 ${days} 天`
  return (
    <div className="stats-grid">
      <StatCard title="平台调用" value={formatNumber(overview.summary.call_count)} detail={`${period}累计`} />
      <StatCard title="消耗积分" value={formatNumber(overview.summary.total_cost)} detail={`${period}实际消耗`} />
      <StatCard title="调用用户" value={formatNumber(overview.summary.user_count)} detail="统计区间内去重用户" />
      <StatCard title="调用服务" value={overview.by_service.length} detail="有调用记录的服务数量" />
    </div>
  )
}
