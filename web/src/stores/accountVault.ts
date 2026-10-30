/** 多账号切换的纯逻辑：不依赖 DOM 与 store，便于单测。 */

export interface SavedAccount {
  /** 登录名，作为唯一键 */
  username: string
  /** 展示名（昵称） */
  displayName: string
  /** user / admin，仅用于展示 */
  role: string
  userId: string
  token: string
  /** 后端返回的过期时间，形如 "2026-10-31 07:58:56" */
  expireAt: string
  savedAt: number
}

/** 最多保留最近登录的 5 个账号，避免本地存储无限增长。 */
export const MAX_ACCOUNTS = 5

/** 从 JWT 载荷里读取 role；只用于界面展示，权限仍由服务端校验。 */
export function decodeRole(token: string): string {
  const payload = token.split('.')[1]
  if (!payload) return 'user'
  try {
    const normalized = payload.replace(/-/g, '+').replace(/_/g, '/')
    const padded = normalized + '='.repeat((4 - (normalized.length % 4)) % 4)
    const parsed: unknown = JSON.parse(atob(padded))
    if (parsed && typeof parsed === 'object' && 'role' in parsed) {
      const role = (parsed as { role?: unknown }).role
      if (typeof role === 'string' && role) return role
    }
  } catch {
    /* 载荷异常按普通用户展示，不阻断登录 */
  }
  return 'user'
}

/** 插入或更新账号，最近使用的排在最前。 */
export function upsertAccount(list: SavedAccount[], account: SavedAccount): SavedAccount[] {
  const rest = list.filter((item) => item.username !== account.username)
  return [account, ...rest].slice(0, MAX_ACCOUNTS)
}

export function removeAccount(list: SavedAccount[], username: string): SavedAccount[] {
  return list.filter((item) => item.username !== username)
}

/** 过期判断：后端时间按本地时区解析，解析失败视为未过期，交给服务端拒绝。 */
export function isExpired(account: SavedAccount, now: number = Date.now()): boolean {
  if (!account.expireAt) return false
  const timestamp = Date.parse(account.expireAt.replace(' ', 'T'))
  return Number.isFinite(timestamp) && timestamp <= now
}
