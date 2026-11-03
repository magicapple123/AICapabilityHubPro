import type { AdminUser } from '@/api/admin'
import { EmptyNote } from '@/components/ui'
import type { UserUsageRow } from '@/features/console/userUsage'
import { formatNumber } from '@/lib/dateRange'

/**
 * 「用户与用量」名单（P5）：一行一个人，左半是 user-service 的资料，
 * 右半是 billing 的消耗。角色/状态/余额/日预算只读，写操作入口在操作列与抽屉里。
 */
export function UserUsageTable({ rows, days, onDetail, onAdjust, onToggle }: {
  rows: UserUsageRow[]
  days: number
  onDetail: (row: UserUsageRow) => void
  onAdjust: (user: AdminUser) => void
  onToggle: (user: AdminUser) => void
}) {
  if (!rows.length) return <EmptyNote message="没有匹配的用户。换个关键词或清空筛选试试。" />
  return (
    <div className="data-table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            <th>用户</th><th>角色</th><th>状态</th><th>余额</th><th>日预算</th>
            <th>近 {days} 天调用</th><th>近 {days} 天消耗</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const user = row.user
            return (
              <tr key={row.user_id} className="row-clickable" onClick={() => onDetail(row)}>
                <td>
                  {user
                    ? <><strong>{user.username}</strong><small className="muted"> #{user.id}</small></>
                    : <><strong>#{row.user_id}</strong><small className="muted"> 资料缺失</small></>}
                </td>
                <td>{user ? (user.role === 'admin' ? '管理员' : '普通用户') : '—'}</td>
                <td>{user ? (user.status === 'normal' ? '正常' : '已禁用') : '—'}</td>
                <td>{user ? formatNumber(user.balance) : '—'}</td>
                <td>{user ? (user.daily_points_limit > 0 ? formatNumber(user.daily_points_limit) : '不限') : '—'}</td>
                <td>{formatNumber(row.call_count)}</td>
                <td><strong>{formatNumber(row.total_cost)}</strong></td>
                <td className="admin-actions" onClick={(event) => event.stopPropagation()}>
                  <button className="text-button" onClick={() => onDetail(row)}>详情</button>
                  {user ? <>
                    <button className="text-button" onClick={() => onToggle(user)}>
                      {user.status === 'normal' ? '禁用' : '启用'}
                    </button>
                    <button className="text-button" onClick={() => onAdjust(user)}>调分</button>
                  </> : <span className="muted text-xs">仅账单</span>}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
