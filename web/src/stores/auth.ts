import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'
import type { LoginData } from '@/api/types'

interface AuthState {
  token: string
  userId: string
  userName: string
  setAuth: (data: LoginData) => void
  clearAuth: () => void
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      token: '',
      userId: '',
      userName: '',
      // user-service 的 user_id 是数字，占位登录是字符串，这里统一成字符串存储。
      setAuth: (data) =>
        set({
          token: data.token,
          userId: data.user_id === undefined ? '' : String(data.user_id),
          userName: data.user_name || data.username || '',
        }),
      clearAuth: () => set({ token: '', userId: '', userName: '' }),
    }),
    { name: 'ai-capability-auth', storage: createJSONStorage(() => localStorage) },
  ),
)
