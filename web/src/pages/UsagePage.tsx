import { ArrowUpRight, BarChart3, Coins, Gauge } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { fetchCallRecords, fetchUsage, type CallRecordItem, type UsageData } from '@/api/billing'
import { fetchPoints, type PointsAccount } from '@/api/user'
import { EmptyNote, ErrorNote, Loading, Pager, StatusTag } from '@/components/ui'

const STATUS_OPTIONS: Array<{ value: '' | 'success' | 'degraded' | 'failed'; label: string }> = [
  { value: '', label: '全部状态' },
  { value: 'success', label: '成功' },
  { value: 'degraded', label: '降级' },
  { value: 'failed', label: '失败' },
]

const PAGE_SIZE = 10

export function UsagePage() {
  const navigate = useNavigate()
  const [points, setPoints] = useState<PointsAccount | null>(null)
  const [usage, setUsage] = useState<UsageData | null>(null)
  const [records, setRecords] = useState<CallRecordItem[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [status, setStatus] = useState<'' | 'success' | 'degraded' | 'failed'>('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [pointsData, usageData, recordPage] = await Promise.all([
        fetchPoints(),
        fetchUsage(),
        fetchCallRecords({
          page,
          page_size: PAGE_SIZE,
          call_status: status || undefined,
        }),
      ])
      setPoints(pointsData)
      setUsage(usageData)
      setRecords(recordPage.list ?? [])
      setTotal(recordPage.total ?? 0)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '用量数据加载失败')
      setRecords([])
      setTotal(0)
    } finally {
      setLoading(false)
    }
  }, [page, status])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    // 切换筛选条件时回到第一页，避免落在空页。
    setPage(1)
  }, [status])

  const summary = usage?.summary
  const successRate =
    summary && summary.call_count > 0
      ? Math.round((summary.success_count / summary.call_count) * 100)
      : 0
  const maxDaily = Math.max(1, ...(usage?.by_day ?? []).map((item) => item.call_count))

  return (
    <section className="mx-auto max-w-[1500px] px-5 pb-32 pt-12 md:px-10 md:pt-20">
      <div className="flex items-end justify-between gap-6">
        <div>
          <p className="mb-5 text-sm text-[#c9f05b]">计量与调用</p>
          <h1 className="text-5xl font-medium tracking-[-.07em] text-[#f4f4ef] md:text-7xl">
            看见每一次
            <br />
            <span className="text-white/35">能力如何被使用。</span>
          </h1>
        </div>
        <button
          onClick={() => navigate('/chat')}
          className="hidden items-center gap-2 text-sm text-white/55 hover:text-[#c9f05b] md:flex"
        >
          再次调试 <ArrowUpRight size={16} />
        </button>
      </div>

      {loading && (
        <div className="mt-16">
          <Loading label="正在加载用量数据…" />
        </div>
      )}

      {!loading && error && (
        <div className="mt-16">
          <ErrorNote message={error} onRetry={() => void load()} />
        </div>
      )}

      {!loading && !error && (
        <>
          <div className="mt-16 grid gap-3 md:grid-cols-3">
            <div className="rounded-[1.5rem] bg-[#c9f05b] p-7 text-[#11130f]">
              <Coins size={22} />
              <p className="mt-16 text-sm font-semibold uppercase tracking-[.18em] text-[#11130f]/55">
                积分余额
              </p>
              <p className="mt-2 text-5xl font-medium tracking-[-.06em]">
                {(points?.balance ?? 0).toLocaleString()}
              </p>
              <p className="mt-2 text-sm text-[#11130f]/60">
                冻结 {(points?.frozen ?? 0).toLocaleString()} · 来自 user-service
              </p>
            </div>
            <div className="rounded-[1.5rem] border border-white/10 bg-[#181c17] p-7">
              <BarChart3 size={22} className="text-[#c9f05b]" />
              <p className="mt-16 text-sm font-semibold uppercase tracking-[.18em] text-white/35">
                调用次数
              </p>
              <p className="mt-2 text-5xl font-medium tracking-[-.06em] text-white">
                {(summary?.call_count ?? 0).toLocaleString()}
              </p>
              <p className="mt-2 text-sm text-white/40">
                成功率 {successRate}% · 统计区间 {(usage?.start_date ?? '').slice(5)} ~{' '}
                {(usage?.end_date ?? '').slice(5)}
              </p>
            </div>
            <div className="rounded-[1.5rem] border border-white/10 bg-[#181c17] p-7">
              <Gauge size={22} className="text-[#c9f05b]" />
              <p className="mt-16 text-sm font-semibold uppercase tracking-[.18em] text-white/35">
                消耗积分
              </p>
              <p className="mt-2 text-5xl font-medium tracking-[-.06em] text-white">
                {(summary?.total_cost ?? 0).toLocaleString()}
              </p>
              <p className="mt-2 text-sm text-white/40">
                降级 {summary?.degraded_count ?? 0} · 失败 {summary?.failed_count ?? 0}（降级不计费）
              </p>
            </div>
          </div>

          <div className="mt-12 grid gap-4 lg:grid-cols-[1.5fr_1fr]">
            <div className="overflow-hidden rounded-[1.5rem] border border-white/10 bg-[#181c17] p-6 md:p-8">
              <div className="flex items-end justify-between">
                <div>
                  <h2 className="text-xl font-medium text-white">按天用量</h2>
                  <p className="mt-1 text-sm text-white/35">数据来自 billing-service 的 t_usage_daily。</p>
                </div>
                <span className="text-xs text-white/35">峰值 {maxDaily} 次</span>
              </div>
              {usage && usage.by_day.length > 0 ? (
                <div className="mt-8 flex h-40 items-end gap-2">
                  {usage.by_day.map((item) => (
                    <div key={item.stat_date} className="group flex flex-1 flex-col items-center gap-2">
                      <span className="text-[10px] text-white/35 opacity-0 transition group-hover:opacity-100">
                        {item.call_count}
                      </span>
                      <div
                        className="w-full rounded-t-md bg-[#c9f05b]/70 transition group-hover:bg-[#c9f05b]"
                        style={{ height: `${Math.max(4, (item.call_count / maxDaily) * 120)}px` }}
                      />
                      <span className="text-[10px] text-white/30">{item.stat_date.slice(5)}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="mt-8">
                  <EmptyNote message="统计区间内还没有调用，去调试台发起一次对话试试。" />
                </div>
              )}
            </div>

            <div className="overflow-hidden rounded-[1.5rem] border border-white/10 bg-[#181c17] p-6 md:p-8">
              <h2 className="text-xl font-medium text-white">按服务分布</h2>
              <p className="mt-1 text-sm text-white/35">同一能力服务被调用的次数与积分。</p>
              {usage && usage.by_service.length > 0 ? (
                <div className="mt-6 space-y-4">
                  {usage.by_service.map((item) => (
                    <div key={item.service_name} className="border-b border-white/10 pb-3 last:border-none">
                      <div className="flex items-center justify-between text-sm text-white">
                        <span>{item.service_name || '未标注服务'}</span>
                        <span>{item.call_count} 次</span>
                      </div>
                      <p className="mt-1 text-xs text-white/40">消耗 {item.total_cost} 积分</p>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="mt-6">
                  <EmptyNote message="暂无服务维度数据。" />
                </div>
              )}
            </div>
          </div>

          <div className="mt-12 overflow-hidden rounded-[1.5rem] border border-white/10 bg-[#181c17]">
            <div className="flex flex-wrap items-center justify-between gap-4 border-b border-white/10 p-6 md:p-8">
              <div>
                <h2 className="text-xl font-medium text-white">最近调用</h2>
                <p className="mt-1 text-sm text-white/35">
                  只能查看自己的调用明细；requestId 可作为全链路排查线索。
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                {STATUS_OPTIONS.map((option) => (
                  <button
                    key={option.value || 'all'}
                    onClick={() => setStatus(option.value)}
                    className={`rounded-full px-3 py-1.5 text-xs transition ${
                      status === option.value
                        ? 'bg-white text-[#11130f]'
                        : 'border border-white/10 text-white/45 hover:border-[#c9f05b] hover:text-[#c9f05b]'
                    }`}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
            </div>

            {records.length === 0 ? (
              <div className="p-6 md:p-8">
                <EmptyNote message="没有符合条件的调用记录。" />
              </div>
            ) : (
              <div className="divide-y divide-white/10">
                {records.map((item) => (
                  <div
                    key={item.id}
                    className="flex flex-wrap items-center justify-between gap-4 p-6 text-sm"
                  >
                    <div className="min-w-[220px]">
                      <p className="text-white">{item.service_name || '未标注服务'}</p>
                      <p className="mt-1 text-xs text-white/35">
                        {item.create_time} · {item.request_id.slice(0, 12)}… · {item.model_name || '—'}
                      </p>
                    </div>
                    <span className="text-white/45">{item.duration_ms} ms</span>
                    <StatusTag value={item.call_status} />
                    <span className="text-white/55">
                      {item.cost > 0 ? `-${item.cost} 积分` : '未计费'}
                    </span>
                  </div>
                ))}
              </div>
            )}

            <div className="border-t border-white/10 p-6 md:p-8">
              <Pager page={page} pageSize={PAGE_SIZE} total={total} onChange={setPage} />
            </div>
          </div>
        </>
      )}
    </section>
  )
}
