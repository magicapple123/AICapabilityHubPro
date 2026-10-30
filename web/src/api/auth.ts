import { request } from './client'
import type { LoginData, LoginPayload, RegisterData, RegisterPayload } from './types'
import { env } from '@/utils/env'

const mockToken = () => env.devToken || 'dev-token-configure-via-VITE_DEV_TOKEN'

/**
 * 登录：默认走本地占位实现（不发起网络请求）；
 * `VITE_USE_MOCK_LOGIN=false` 时调用网关 `/api/user/login`。
 *
 * user-service 契约返回 `user_id`（数字）与 `username`，这里归一化成
 * store 使用的 `user_name`，避免页面层再判断字段。
 */
export const login = async (payload: LoginPayload): Promise<LoginData> => {
  if (env.useMockLogin) {
    const name = payload.username || 'dev-user'
    return { token: mockToken(), user_id: 'dev-user', user_name: name, username: name }
  }
  const data = await request<LoginData>({ method: 'POST', url: '/user/login', data: payload })
  return {
    token: data.token,
    user_id: data.user_id,
    // 保留登录名与过期时间：多账号切换需要稳定唯一键，也要能判断令牌是否过期。
    username: data.username || payload.username,
    user_name: data.username || data.user_name || payload.username,
    expire_at: data.expire_at,
  }
}

/** 注册：网关白名单接口，注册成功即创建积分账户并赠送初始积分。 */
export const register = (payload: RegisterPayload) =>
  request<RegisterData>({ method: 'POST', url: '/user/register', data: payload })
