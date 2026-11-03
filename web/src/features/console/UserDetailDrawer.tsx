import { App, Drawer, InputNumber } from 'antd'
import { Download, ReceiptText } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { fetchAdminUser, setAdminUserBudget } from '@/api/admin'
import {
  fetchAdminCallRecords, fetchAdminUserKeyUsage, fetchAdminUserUsage,
  type KeyUsageAggregate,
} from '@/api/billing'
import { EmptyNote, ErrorNote, Loading, StatusTag } from '@/components/ui'
import { StatCard } from '@/components/StatCard'
import type { UserUsageRow } from '@/features/console/userUsage'
import { RecordTable } from '@/features/usage/RecordTable'
import { UsageChart } from '@/features/usage/UsageChart'
import { exportRecords } from '@/features/usage/exportRecords'
import { useAsyncResource } from '@/hooks/useAsyncResource'
import { dateRange, formatNumber } from '@/lib/dateRange'

const MAX_BUDGET = 1_000_000

/**
 * 用户详情抽屉：余额 / 日预算（P10）/ 用量趋势 / 最近调用（可按 Key 筛选，P6）/
 * Key 列表与按 Key 的调用分布。只看元数据，不展示会话正文与任何 Key 的 secret。
 */
export function UserDetailDrawer({ row, days, onClose, onChanged }: {
  row: UserUsageRow | null
  days: number
  onClose: () => void
  onChanged: () => void
}) {
  const { message } = App.useApp()
  const userId = row?.user_id ?? null
  const [apiKeyId, setApiKeyId] = useState<number | ''>('')
  const [exporting, setExporting] = useState(false)
  const [budgetDraft, setBudgetDraft] = useState(0)
  const [savingBudget, setSavingBudget] = useState(false)
  const [budgetError, setBudgetError] = useState('')

  const load = useCallback(async () => {
    if (!userId) return null
    const range = dateRange(days)
    const [detail, usage, records, keyUsage] = await Promise.all([
      fetchAdminUser(userId),
      fetchAdminUserUsage(userId, range).catch(() => null),
      fetchAdminCallRecords({
        user_id: userId, page_size: 10, ...range, api_key_id: apiKeyId || undefined,
      }).catch(() => null),
      fetchAdminUserKeyUsage(userId, range).catch(() => null),
    ])
    return { detail, usage, records: records?.list ?? [], keyUsage: keyUsage?.list ?? [] }
  }, [userId, days, apiKeyId])
  const resource = useAsyncResource(load)
  const detail = resource.data?.detail
  const usage = resource.data?.usage ?? detail?.usage ?? null
  const records = resource.data?.records ?? []
  const keyUsage = resource.data?.keyUsage ?? []

  useEffect(() => { setApiKeyId(''); setBudgetError('') }, [userId])
  useEffect(() => { if (detail) setBudgetDraft(detail.daily_points_limit) }, [detail])

  const exportUsage = async () => {
    if (!userId) return
    setExporting(true)
    try {
      const page = await fetchAdminCallRecords({
        user_id: userId, page_size: 100, ...dateRange(days), api_key_id: apiKeyId || undefined,
      })
      exportRecords(page.list)
    } catch (cause) {
      void message.error(cause instanceof Error ? cause.message : '导出失败')
    } finally {
      setExporting(false)
    }
  }

  const saveBudget = async () => {
    if (!detail || savingBudget) return
    setSavingBudget(true)
    setBudgetError('')
    try {
      const result = await setAdminUserBudget(detail.id, budgetDraft)
      void message.success(result.daily_points_limit > 0
        ? `日预算已设为 ${formatNumber(result.daily_points_limit)} 积分`
        : '日预算已改为不限')
      resource.reload()
      onChanged()
    } catch (cause) {
      setBudgetError(cause instanceof Error ? cause.message : '日预算保存失败')
    } finally {
      setSavingBudget(false)
    }
  }

  const keyName = (id: number) => detail?.api_keys?.find((key) => key.id === id)?.name || `Key #${id}`

  return (
    <Drawer
      open={!!row} onClose={onClose} width={760} destroyOnHidden
      title={row ? `用户详情 · ${row.user?.username ?? `#${row.user_id}`} #${row.user_id}` : '用户详情'}
    >
      {resource.loading && !detail ? <Loading label="正在读取用户详情…" /> : null}
      {resource.error ? <ErrorNote message={resource.error} onRetry={resource.reload} /> : null}
      {detail ? (
        <div className="user-detail">
          <div className="stats-grid" style={{ marginBottom: 16 }}>
            <StatCard title="余额" value={`${formatNumber(detail.balance)} 积分`} detail="当前可用积分" />
            <StatCard title="今日消耗" value={`${formatNumber(detail.today_used)} 积分`} detail="按调用流水统计" />
            <StatCard title="账号状态" value={<StatusTag value={detail.status} />}
              detail={detail.role === 'admin' ? '管理员' : '普通用户'} />
          </div>

          <section className="panel" style={{ marginBottom: 16 }}>
            <div className="panel-head">
              <div><h3>日预算</h3><p>0 = 不限；超出当日预算的调用返回 3003，与余额不足（3001）是两个闸门。</p></div>
            </div>
            <div className="panel-body user-budget">
              <InputNumber
                value={budgetDraft} onChange={(value) => setBudgetDraft(value ?? 0)}
                min={0} max={MAX_BUDGET} precision={0} step={10} disabled={savingBudget}
                addonAfter="积分 / 天" style={{ width: 200 }}
              />
              <button className="button-primary" disabled={savingBudget || budgetDraft === detail.daily_points_limit}
                onClick={() => void saveBudget()}>{savingBudget ? '保存中…' : '保存预算'}</button>
              <span className="muted text-xs">
                当前：{detail.daily_points_limit > 0 ? `${formatNumber(detail.daily_points_limit)} 积分 / 天` : '不限'}
              </span>
            </div>
            {budgetError ? <div className="panel-body"><ErrorNote message={budgetError} /></div> : null}
          </section>

          <section className="panel" style={{ marginBottom: 16 }}>
            <div className="panel-head">
              <h3>近 {days} 天用量</h3>
              <button className="text-button" disabled={exporting} onClick={() => void exportUsage()}>
                <Download size={13} /> {exporting ? '导出中…' : '导出调用明细 CSV'}
              </button>
            </div>
            {usage
              ? <div className="panel-body"><UsageChart usage={usage} /></div>
              : <EmptyNote message="用量数据暂不可用（billing-service 未返回），稍后重试。" />}
          </section>

          <section className="panel" style={{ marginBottom: 16 }}>
            <div className="panel-head">
              <h3><ReceiptText size={14} /> 最近 10 条调用</h3>
              <div className="inline-form">
                <select
                  aria-label="按 API Key 筛选调用" value={String(apiKeyId)}
                  onChange={(event) => setApiKeyId(event.target.value ? Number(event.target.value) : '')}
                >
                  <option value="">全部 Key</option>
                  {(detail.api_keys ?? []).map((key) => (
                    <option key={key.id} value={key.id}>{key.name || `Key #${key.id}`}</option>
                  ))}
                </select>
              </div>
            </div>
            <RecordTable records={records} compact />
          </section>

          <section className="panel" style={{ marginBottom: 16 }}>
            <div className="panel-head"><h3>API Key（{detail.api_keys?.length ?? 0}）</h3></div>
            {detail.api_keys?.length ? (
              <div className="data-table-wrap">
                <table className="data-table">
                  <thead><tr><th>名称</th><th>Access Key</th><th>状态</th><th>创建时间</th></tr></thead>
                  <tbody>
                    {detail.api_keys.map((key) => (
                      <tr key={key.id}>
                        <td>{key.name || '未命名'}</td>
                        <td className="mono text-xs">{key.access_key}</td>
                        <td><StatusTag value={key.status} /></td>
                        <td className="mono text-xs">{key.create_time}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <EmptyNote message="该用户还没有 API Key。" />}
          </section>

          <section className="panel">
            <div className="panel-head">
              <div><h3>按 Key 的调用分布</h3><p>近 {days} 天；历史记录没有 Key 身份，不计入本表。</p></div>
            </div>
            <KeyUsageTable rows={keyUsage} keyName={keyName} />
          </section>
        </div>
      ) : null}
    </Drawer>
  )
}

function KeyUsageTable({ rows, keyName }: { rows: KeyUsageAggregate[]; keyName: (id: number) => string }) {
  if (!rows.length) return <EmptyNote message="统计区间内没有带 Key 身份的调用。" />
  return (
    <div className="data-table-wrap">
      <table className="data-table">
        <thead><tr><th>Key</th><th>Key 编号</th><th>调用次数</th><th>消耗积分</th><th>最近使用</th></tr></thead>
        <tbody>
          {rows.map((item) => (
            <tr key={item.api_key_id}>
              <td>{keyName(item.api_key_id)}</td>
              <td className="mono text-xs">#{item.api_key_id}</td>
              <td>{formatNumber(item.call_count)}</td>
              <td>{formatNumber(item.total_cost)}</td>
              <td className="record-time">{item.last_call_at ? item.last_call_at.replace('T', ' ').slice(0, 19) : '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
