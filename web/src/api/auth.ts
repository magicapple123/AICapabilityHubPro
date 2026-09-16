import { request } from './client'
import type { LoginData, LoginPayload } from './types'
import { env } from '@/utils/env'

const mockToken = () => env.devToken || 'dev-token-configure-via-VITE_DEV_TOKEN'

export const login = async (payload: LoginPayload): Promise<LoginData> => {
  if (env.useMockLogin) {
    return { token: mockToken(), user_id: 'dev-user', user_name: payload.username || '开发者' }
  }
  return request<LoginData>({ method: 'POST', url: '/user/login', data: payload })
}
