import { App } from 'antd'
import { ChevronDown, ChevronRight, Download, RefreshCw } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { downloadAdminUsers, fetchAdminUsers, setAdminUserStatus, type AdminUser } from '@/api/admin'
import { fetchAdminUserAggregates, fetchOverview, type OverviewData } from '@/api/billing'
import { ErrorNote, Loading, Pager } from '@/components/ui'
import { PlatformStatCards } from '@/features/console/PlatformStatCards'
import { PointsAdjustModal } from '@/features/console/PointsAdjustModal'
import { UserDetailDrawer } from '@/features/console/UserDetailDrawer'
import { UserUsageTable } from '@/features/console/UserUsageTable'
import {
  describeLoadError, joinUserUsage, sortUserUsage,
  type UserSortKey, type UserUsageRow,
} from '@/features/console/userUsage'
import { UsageChart } from '@/features/usage/UsageChart'
import { dateRange } from '@/lib/dateRange'

const RANGES = [7, 30, 90]
const PAGE_SIZE = 20
/**
 * P5 方案 A1 的边界：一次拉全量用户再与 billing 的消耗聚合 join。
 * `/api/user/admin/users` 的管理端 page_size 上限就是 2000（ADMIN_USER_PAGE_SIZE_MAX），
 * 因此 A1 只在**用户总数 ≤ 2000** 时成立；超过后必须升级为 A2：
 * billing 主导分页与排序（它拥有 cost）→ 用 user-service 批量接口补齐姓名/状态，
 * 零调用用户由 user 侧按注册时间补尾页。见 docs/升级需求清单-2026-11-03.md 的 P5 第 8 条。
 */
const USER_FETCH_LIMIT = 2000
const TREND_STORAGE_KEY = 'console.users-usage.trend'
const SORTS: { key: UserSortKey; label: string }[] = [
  { key: 'cost', label: '消耗降序' },
  { key: 'calls', label: '调用次数降序' },
  { key: 'created', label: '注册时间降序' },
]

interface PanelData {
  rows: UserUsageRow[]
  overview: OverviewData
  truncated: number
}

/** 趋势默认收起，避免用户表被挤出首屏；状态记在 localStorage。 */
function readTrendCollapsed() {
  try {
    return window.localStorage.getItem(TREND_STORAGE_KEY) !== 'open'
  } catch {
    return true
  }
}

/**
 * 「用户与用量」（P5，方案 A 完整合并）：平台级统计 + 趋势 + 用户名单三层。
 * 排行不再单列，而是名单的一种排序（默认消耗降序 = 原「积分消耗排行」）。
 */
export function UserUsagePanel() {
  const { message, modal } = App.useApp()
  const [days, setDays] = useState(30)
  const [keywordInput, setKeywordInput] = useState('')
  const [keyword, setKeyword] = useState('')
  const [status, setStatus] = useState<'' | 'normal' | 'disabled'>('')
  const [role, setRole] = useState<'' | 'admin' | 'user'>('')
  const [sort, setSort] = useState<UserSortKey>('cost')
  const [page, setPage] = useState(1)
  const [version, setVersion] = useState(0)
  const [collapsed, setCollapsed] = useState(readTrendCollapsed)
  const [detail, setDetail] = useState<UserUsageRow | null>(null)
  const [adjusting, setAdjusting] = useState<AdminUser | null>(null)
  const [state, setState] = useState<{ data: PanelData | null; error: string; loading: boolean }>({
    data: null, error: '', loading: true,
  })

  useEffect(() => {
    const timer = window.setTimeout(() => setKeyword(keywordInput.trim()), 350)
    return () => window.clearTimeout(timer)
  }, [keywordInput])

  useEffect(() => {
    let active = true
    setState((previous) => ({ ...previous, loading: true, error: '' }))
    void (async () => {
      try {
        const range = dateRange(days)
        const [users, aggregates, overview] = await Promise.all([
          fetchAdminUsers({
            keyword: keyword || undefined, status: status || undefined,
            page: 1, page_size: USER_FETCH_LIMIT,
          }),
          fetchAdminUserAggregates(range),
          fetchOverview(range),
        ])
        if (!active) return
        setState({
          data: {
            rows: joinUserUsage(users.list, aggregates.list),
            overview,
            truncated: Math.max(0, users.total - users.list.length),
          },
          error: '',
          loading: false,
        })
      } catch (cause) {
        if (!active) return
        setState({ data: null, error: describeLoadError(cause), loading: false })
      }
    })()
    return () => { active = false }
  }, [days, keyword, status, version])

  useEffect(() => { setPage(1) }, [days, keyword, status, role, sort])

  const rows = useMemo(() => state.data?.rows ?? [], [state.data])
  const visibleRows = useMemo(
    () => sortUserUsage(rows.filter((row) => !role || row.user?.role === role), sort),
    [rows, role, sort],
  )
  const pageCount = Math.max(1, Math.ceil(visibleRows.length / PAGE_SIZE))
  const safePage = Math.min(page, pageCount)
  const pageRows = visibleRows.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE)
  const activeUsers = rows.filter((row) => row.call_count > 0).length
  const range = dateRange(days)

  const reload = () => setVersion((value) => value + 1)

  const toggleTrend = () => {
    const next = !collapsed
    setCollapsed(next)
    try {
      window.localStorage.setItem(TREND_STORAGE_KEY, next ? 'closed' : 'open')
    } catch {
      // 隐私模式下 localStorage 不可写，折叠仍生效，只是不记忆。
    }
  }

  const toggle = (user: AdminUser) => {
    const next = user.status === 'normal' ? 'disabled' : 'normal'
    modal.confirm({
      title: `${next === 'disabled' ? '禁用' : '启用'}用户「${user.username}」？`,
      content: next === 'disabled'
        ? '禁用后该用户的受保护接口返回 1005，历史调用与账单保留。'
        : '启用后该用户可继续调用能力。',
      okText: next === 'disabled' ? '确认禁用' : '确认启用',
      cancelText: '取消',
      okButtonProps: { danger: next === 'disabled' },
      onOk: async () => {
        try {
          await setAdminUserStatus(user.id, next)
          void message.success('状态已更新')
          reload()
        } catch (cause) {
          void message.error(cause instanceof Error ? cause.message : '操作失败')
          throw cause
        }
      },
    })
  }

  const data = state.data

  return (
    <div>
      <div className="usage-range">
        <span className="muted">统计区间</span>
        <div className="segmented">{RANGES.map((day) => (
          <button key={day} aria-pressed={days === day} onClick={() => setDays(day)}>近 {day} 天</button>
        ))}</div>
        <span className="usage-range-date">{range.start_date} — {range.end_date}</span>
        <button className="button-secondary" onClick={reload} disabled={state.loading}>
          <RefreshCw size={14} />刷新
        </button>
      </div>

      {state.loading && !data ? <Loading label="正在读取用户与用量…" /> : null}
      {state.error ? <ErrorNote message={state.error} onRetry={reload} /> : null}

      {data && !state.error ? <>
        <PlatformStatCards overview={data.overview} days={days} />

        <section className="panel" style={{ marginBottom: 14 }}>
          <div className="panel-head">
            <div><h2>平台调用趋势</h2><p>近 {days} 天每日调用次数，折叠状态会被记住。</p></div>
            <button className="text-button" aria-expanded={!collapsed} onClick={toggleTrend}>
              {collapsed ? <ChevronRight size={13} /> : <ChevronDown size={13} />}
              {collapsed ? '展开趋势' : '收起趋势'}
            </button>
          </div>
          {collapsed ? null
            : <div className="panel-body user-usage-trend"><UsageChart usage={data.overview} /></div>}
        </section>

        <section className="panel">
          <div className="panel-head">
            <div>
              <h2>用户与用量</h2>
              <p>共 {rows.length} 人 · 近 {days} 天有调用 {activeUsers} 人 · 未调用的用户同样保留（消耗 0）</p>
            </div>
            <div className="inline-form">
              <input
                aria-label="搜索用户" placeholder="ID / 用户名 / 昵称"
                value={keywordInput} onChange={(event) => setKeywordInput(event.target.value)}
              />
              <select
                aria-label="按状态筛选" value={status}
                onChange={(event) => setStatus(event.target.value as '' | 'normal' | 'disabled')}
              >
                <option value="">全部状态</option>
                <option value="normal">正常</option>
                <option value="disabled">已禁用</option>
              </select>
              <select
                aria-label="按角色筛选" value={role}
                onChange={(event) => setRole(event.target.value as '' | 'admin' | 'user')}
              >
                <option value="">全部角色</option>
                <option value="admin">管理员</option>
                <option value="user">普通用户</option>
              </select>
              <button
                className="text-button"
                onClick={() => void downloadAdminUsers({ keyword: keyword || undefined, status: status || undefined })}
              >
                <Download size={13} /> 导出名单 CSV
              </button>
            </div>
          </div>

          <div className="usage-toolbar">
            <div className="segmented" aria-label="排序方式">{SORTS.map((item) => (
              <button key={item.key} aria-pressed={sort === item.key} onClick={() => setSort(item.key)}>
                {item.label}
              </button>
            ))}</div>
            <span className="muted text-xs">
              排序作用于 join 后的全量 {visibleRows.length} 人，不是当前页的前 {PAGE_SIZE} 人
            </span>
          </div>

          {data.truncated > 0 ? (
            <p className="muted text-xs" style={{ padding: '0 16px 10px' }}>
              已达到 {USER_FETCH_LIMIT} 用户上限，还有 {data.truncated} 人未载入（A1 方案边界，
              超过后需改造为 billing 主导分页 + 批量补资料）。
            </p>
          ) : null}

          <UserUsageTable
            rows={pageRows} days={days}
            onDetail={setDetail} onAdjust={setAdjusting} onToggle={toggle}
          />
          <Pager page={safePage} pageSize={PAGE_SIZE} total={visibleRows.length} onChange={setPage} />
        </section>
      </> : null}

      {/* key 让抽屉在切换用户时重置本地状态（Key 筛选、预算草稿）。 */}
      <UserDetailDrawer
        key={detail?.user_id ?? 'none'} row={detail} days={days}
        onClose={() => setDetail(null)} onChanged={reload}
      />
      {adjusting ? (
        <PointsAdjustModal
          user={adjusting} onClose={() => setAdjusting(null)}
          onAdjusted={() => { setAdjusting(null); reload() }}
        />
      ) : null}
    </div>
  )
}
