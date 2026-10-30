import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'
import type { LoginData } from '@/api/types'
import {
  decodeRole,
  isExpired,
  removeAccount,
  upsertAccount,
  type SavedAccount,
} from './accountVault'

interface AuthState {
  token: string
  userId: string
  userName: string
  /** 当前登录名，用于在账号列表里定位自己 */
  username: string
  role: string
  /** 本机登录过的账号；只存令牌，不存密码 */
  accounts: SavedAccount[]
  setAuth: (data: LoginData) => void
  /** 退出登录：清会话并把这个账号从列表里移除 */
  clearAuth: () => void
  /** 仅清会话，保留账号列表（用于“使用其他账号登录”） */
  dropSession: () => void
  /** 切换到已保存的账号；账号不存在或已过期返回 false */
  switchTo: (username: string) => boolean
  removeSavedAccount: (username: string) => void
}

const EMPTY_SESSION = { token: '', userId: '', userName: '', username: '', role: '' }

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      ...EMPTY_SESSION,
      accounts: [],
      // user-service 的 user_id 是数字，占位登录是字符串，这里统一成字符串存储。
      setAuth: (data) =>
        set((state) => {
          const token = data.token
          const username = data.username || state.username || ''
          const displayName = data.user_name || data.username || username
          const userId = data.user_id === undefined ? '' : String(data.user_id)
          const account: SavedAccount = {
            username,
            displayName,
            role: decodeRole(token),
            userId,
            token,
            expireAt: data.expire_at ?? '',
            savedAt: Date.now(),
          }
          return {
            token,
            userId,
            userName: displayName,
            username,
            role: account.role,
            accounts: username ? upsertAccount(state.accounts, account) : state.accounts,
          }
        }),
      clearAuth: () =>
        set((state) => ({
          ...EMPTY_SESSION,
          accounts: removeAccount(state.accounts, state.username),
        })),
      dropSession: () => set({ ...EMPTY_SESSION }),
      switchTo: (username) => {
        const account = get().accounts.find((item) => item.username === username)
        if (!account || isExpired(account)) return false
        set({
          token: account.token,
          userId: account.userId,
          userName: account.displayName,
          username: account.username,
          role: account.role,
        })
        return true
      },
      removeSavedAccount: (username) =>
        set((state) => ({ accounts: removeAccount(state.accounts, username) })),
    }),
    { name: 'ai-capability-auth', storage: createJSONStorage(() => localStorage) },
  ),
)
