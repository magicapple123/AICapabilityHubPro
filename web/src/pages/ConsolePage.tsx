import { Activity, Coins, ShieldCheck, Users } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'

import { fetchOverview, type OverviewData } from '@/api/billing'
import { CapabilityManager } from '@/components/CapabilityManager'
import { CategoryManager } from '@/components/CategoryManager'
import { EmptyNote, ErrorNote, Loading } from '@/components/ui'

/**
 * 运营后台：全局用量统计 + 分类管理 + 能力登记与上下架。
 *
 * 平台本期没有角色体系（契约第 6 节待确认），所有已登录用户均可访问；
 * 未登录访问仍会被网关拦截并跳转 `/login`。
 */
export function ConsolePage() {
  const [overview, setOverview] = useState<OverviewData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setOverview(await fetchOverview())
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '全局统计加载失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const summary = overview?.summary
  const successRate =
    summary && summary.call_count > 0
      ? Math.round((summary.success_count / summary.call_count) * 100)
      : 0

  return (
    <section className="mx-auto max-w-[1500px] px-5 pb-32 pt-12 md:px-10 md:pt-20">
      <p className="mb-5 text-sm text-[#c9f05b]">运营后台</p>
      <h1 className="text-5xl font-medium tracking-[-.07em] text-[#f4f4ef] md:text-7xl">
        供给与治理
        <br />
        <span className="text-white/35">都在这里。</span>
      </h1>

      <div className="mt-16">
        {loading && <Loading label="正在加载全局统计…" />}
        {!loading && error && <ErrorNote message={error} onRetry={() => void load()} />}
        {!loading && !error && overview && (
          <>
            <div className="grid gap-3 md:grid-cols-4">
              <div className="rounded-[1.5rem] bg-[#c9f05b] p-7 text-[#11130f]">
                <Activity size={22} />
                <p className="mt-14 text-xs font-semibold uppercase tracking-[.18em] text-[#11130f]/55">
                  平台调用次数
                </p>
                <p className="mt-2 text-4xl font-medium tracking-[-.06em]">
                  {(summary?.call_count ?? 0).toLocaleString()}
                </p>
                <p className="mt-2 text-sm text-[#11130f]/60">成功率 {successRate}%</p>
              </div>
              <div className="rounded-[1.5rem] border border-white/10 bg-[#181c17] p-7">
                <Coins size={22} className="text-[#c9f05b]" />
                <p className="mt-14 text-xs font-semibold uppercase tracking-[.18em] text-white/35">
                  消耗积分
                </p>
                <p className="mt-2 text-4xl font-medium tracking-[-.06em] text-white">
                  {(summary?.total_cost ?? 0).toLocaleString()}
                </p>
                <p className="mt-2 text-sm text-white/40">
                  降级 {summary?.degraded_count ?? 0} · 失败 {summary?.failed_count ?? 0}
                </p>
              </div>
              <div className="rounded-[1.5rem] border border-white/10 bg-[#181c17] p-7">
                <Users size={22} className="text-[#c9f05b]" />
                <p className="mt-14 text-xs font-semibold uppercase tracking-[.18em] text-white/35">
                  活跃用户
                </p>
                <p className="mt-2 text-4xl font-medium tracking-[-.06em] text-white">
                  {summary?.user_count ?? 0}
                </p>
                <p className="mt-2 text-sm text-white/40">
                  统计区间 {(overview.start_date ?? '').slice(5)} ~{' '}
                  {(overview.end_date ?? '').slice(5)}
                </p>
              </div>
              <div className="rounded-[1.5rem] border border-white/10 bg-[#181c17] p-7">
                <ShieldCheck size={22} className="text-[#c9f05b]" />
                <p className="mt-14 text-xs font-semibold uppercase tracking-[.18em] text-white/35">
                  承载服务
                </p>
                <p className="mt-2 text-4xl font-medium tracking-[-.06em] text-white">
                  {overview.by_service.length}
                </p>
                <p className="mt-2 text-sm text-white/40">按服务维度聚合的调用来源</p>
              </div>
            </div>

            <div className="mt-4 grid gap-4 lg:grid-cols-2">
              <div className="rounded-[1.5rem] border border-white/10 bg-[#181c17] p-6 md:p-8">
                <h2 className="text-xl font-medium text-white">消耗排行</h2>
                <p className="mt-1 text-sm text-white/35">按消耗积分倒序取前 10 名用户。</p>
                {overview.top_users.length === 0 ? (
                  <div className="mt-6">
                    <EmptyNote message="统计区间内还没有用户调用。" />
                  </div>
                ) : (
                  <div className="mt-6 divide-y divide-white/10">
                    {overview.top_users.map((item, index) => (
                      <div
                        key={item.user_id}
                        className="flex items-center justify-between gap-4 py-3 text-sm"
                      >
                        <span className="text-white/35">#{index + 1}</span>
                        <span className="flex-1 text-white">用户 {item.user_id}</span>
                        <span className="text-white/45">{item.call_count} 次</span>
                        <span className="text-[#c9f05b]">{item.total_cost} 积分</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div className="rounded-[1.5rem] border border-white/10 bg-[#181c17] p-6 md:p-8">
                <h2 className="text-xl font-medium text-white">服务用量</h2>
                <p className="mt-1 text-sm text-white/35">各能力服务的调用次数与积分消耗。</p>
                {overview.by_service.length === 0 ? (
                  <div className="mt-6">
                    <EmptyNote message="统计区间内还没有服务调用。" />
                  </div>
                ) : (
                  <div className="mt-6 divide-y divide-white/10">
                    {overview.by_service.map((item) => (
                      <div
                        key={item.service_name}
                        className="flex items-center justify-between gap-4 py-3 text-sm"
                      >
                        <span className="flex-1 text-white">
                          {item.service_name || '未标注服务'}
                        </span>
                        <span className="text-white/45">{item.call_count} 次</span>
                        <span className="text-white/55">{item.total_cost} 积分</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </>
        )}
      </div>

      <div className="mt-8 space-y-4">
        <CategoryManager onChanged={() => void load()} />
        <CapabilityManager onChanged={() => void load()} />
      </div>
    </section>
  )
}
