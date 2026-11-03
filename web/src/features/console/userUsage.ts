import type { AdminUser } from '@/api/admin'
import type { UserUsageAggregate } from '@/api/billing'

/**
 * join 后的一行：`user === null` 表示 billing 有消耗、但 user-service 没返回该用户
 * （账号被物理删除或超出 2000 上限）。这类行仍要展示 `#id`，不允许整行消失。
 */
export interface UserUsageRow {
  user_id: number
  user: AdminUser | null
  call_count: number
  total_cost: number
  last_call_at: string | null
}

export type UserSortKey = 'cost' | 'calls' | 'created'

/**
 * 前端 join（P5 方案 A1）：用户资料来自 user-service，消耗来自 billing，
 * 两个服务禁止跨库，因此在这里按 user_id 对齐。billing 无记录 → 0 次 / 0 积分。
 */
export function joinUserUsage(
  users: AdminUser[], aggregates: UserUsageAggregate[],
): UserUsageRow[] {
  const rows: UserUsageRow[] = users.map((user) => ({
    user_id: user.id, user, call_count: 0, total_cost: 0, last_call_at: null,
  }))
  const index = new Map(rows.map((row) => [row.user_id, row]))
  for (const item of aggregates) {
    const row = index.get(item.user_id)
    if (!row) {
      // user 侧缺资料的兜底行：保证"有消耗就有人"，排序列仍可用。
      rows.push({
        user_id: item.user_id, user: null,
        call_count: item.call_count, total_cost: item.total_cost, last_call_at: item.last_call_at,
      })
      continue
    }
    row.call_count = item.call_count
    row.total_cost = item.total_cost
    row.last_call_at = item.last_call_at
  }
  return rows
}

/** 排序作用于 join 后的全量数据（不是当前页的前 N 人）。 */
export function sortUserUsage(rows: UserUsageRow[], sort: UserSortKey): UserUsageRow[] {
  const copy = [...rows]
  if (sort === 'calls') copy.sort((a, b) => b.call_count - a.call_count)
  else if (sort === 'created') {
    // 资料缺失的行没有注册时间，排在末尾而不是打乱顺序。
    copy.sort((a, b) => (b.user?.create_time ?? '').localeCompare(a.user?.create_time ?? ''))
  } else copy.sort((a, b) => b.total_cost - a.total_cost)
  return copy
}

/**
 * 权限失败统一文案：后端在 user-service 用 `2007 无运营权限`、
 * 在 billing 的 `/stat/overview` 用 `1006 权限不足` 两种口径，
 * 这里收敛成一句，避免同一页出现两套说法（不影响服务端判定，前端不做权限拦截）。
 */
export function describeLoadError(cause: unknown): string {
  const message = cause instanceof Error ? cause.message : '加载失败，请稍后重试'
  const code = (cause as { result?: { code?: number } } | null)?.result?.code
  return code === 2007 || code === 1006 ? '权限不足：仅管理员可访问「用户与用量」。' : message
}
