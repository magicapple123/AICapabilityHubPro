import { useCallback, useState } from 'react'
import { Download, UserCog } from 'lucide-react'
import {
  adjustAdminUserPoints, downloadAdminUsers, fetchAdminUsers,
  setAdminUserStatus, type AdminUser,
} from '@/api/admin'
import { EmptyNote, ErrorNote, Loading } from '@/components/ui'
import { useAsyncResource } from '@/hooks/useAsyncResource'
import { formatNumber } from '@/lib/dateRange'

/**
 * 用户管理（F1）：搜索、启停、调分、导出。
 * 所有写操作都以服务端管理员校验为准，前端不做权限判断。
 */
export function UserAdminPanel() {
  const [keyword, setKeyword] = useState('')
  const [status, setStatus] = useState<'' | 'normal' | 'disabled'>('')
  const load = useCallback(
    () => fetchAdminUsers({
      keyword: keyword || undefined,
      status: status || undefined,
      page_size: 50,
    }),
    [keyword, status],
  )
  const resource = useAsyncResource(load)
  const rows = resource.data?.list ?? []

  const toggle = async (user: AdminUser) => {
    await setAdminUserStatus(user.id, user.status === 'normal' ? 'disabled' : 'normal')
    resource.reload()
  }

  const adjust = async (user: AdminUser) => {
    const raw = window.prompt(`调整积分（正数增加、负数扣减），当前余额 ${user.balance}`)
    if (!raw) return
    const amount = Number(raw)
    if (!Number.isInteger(amount) || amount === 0) {
      window.alert('请输入非 0 整数')
      return
    }
    const reason = window.prompt('调整原因（必填，会写入审计）')
    if (!reason) return
    try {
      await adjustAdminUserPoints(user.id, amount, reason)
      resource.reload()
    } catch (error) {
      window.alert(error instanceof Error ? error.message : '调整失败')
    }
  }

  return (
    <div className="panel">
      <div className="panel-head">
        <h2><UserCog size={16} /> 用户管理</h2>
        <div className="inline-form">
          <input
            placeholder="用户名 / 昵称"
            value={keyword}
            onChange={(event) => setKeyword(event.target.value)}
          />
          <select value={status} onChange={(event) => setStatus(event.target.value as '' | 'normal' | 'disabled')}>
            <option value="">全部状态</option>
            <option value="normal">正常</option>
            <option value="disabled">已禁用</option>
          </select>
          <button
            className="text-button"
            onClick={() => downloadAdminUsers({ keyword, status: status || undefined })}
          >
            <Download size={13} /> 导出 CSV
          </button>
        </div>
      </div>
      <p className="muted text-xs" style={{ padding: '0 16px 8px' }}>
        调分必须填原因，会以 <code>admin_adjust</code> 写入流水并留审计；禁用后该用户所有受保护接口返回 1005。
      </p>
      {resource.loading && !resource.data ? <Loading label="正在读取用户…" /> : null}
      {resource.error ? <ErrorNote message={resource.error} onRetry={resource.reload} /> : null}
      {!resource.loading && !rows.length ? <EmptyNote message="没有匹配的用户。" /> : null}
      {rows.length ? (
        <div className="data-table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>用户</th><th>角色</th><th>状态</th><th>余额</th><th>日预算</th><th>注册时间</th><th>操作</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((user) => (
                <tr key={user.id}>
                  <td><strong>{user.username}</strong><small className="muted"> #{user.id}</small></td>
                  <td>{user.role}</td>
                  <td>{user.status === 'normal' ? '正常' : '已禁用'}</td>
                  <td>{formatNumber(user.balance)}</td>
                  <td>{user.daily_points_limit > 0 ? formatNumber(user.daily_points_limit) : '不限'}</td>
                  <td className="mono text-xs">{user.create_time}</td>
                  <td className="admin-actions">
                    <button className="text-button" onClick={() => toggle(user)}>
                      {user.status === 'normal' ? '禁用' : '启用'}
                    </button>
                    <button className="text-button" onClick={() => adjust(user)}>调分</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  )
}
