import axios, { type AxiosRequestConfig, type AxiosError } from 'axios'
import type { Result } from './types'
import { env } from '@/utils/env'
import { useAuthStore } from '@/stores/auth'

export const apiClient = axios.create({
  baseURL: env.apiBaseUrl, timeout: 15_000, headers: { 'Content-Type': 'application/json' },
})
function redirectToLogin() {
  useAuthStore.getState().clearAuth()
  if (!['/login', '/register'].includes(window.location.pathname)) {
    const redirect = window.location.pathname + window.location.search + window.location.hash
    window.location.assign('/login?redirect=' + encodeURIComponent(redirect))
  }
}
function failure(body: Result<unknown> | undefined, fallback: string) {
  return Object.assign(new Error(body?.message || fallback), { result: body })
}
apiClient.interceptors.request.use((config) => {
  const token = useAuthStore.getState().token
  if (token) config.headers.Authorization = 'Bearer ' + token
  return config
})
apiClient.interceptors.response.use(
  (response) => {
    const body = response.data as Result<unknown> | undefined
    if (body && typeof body.code === 'number') {
      if (body.code !== 0) {
        if (body.code === 1001) redirectToLogin()
        return Promise.reject(failure(body, '操作未完成，请稍后重试'))
      }
      response.data = body.data
    }
    return response
  },
  (error: AxiosError<Result<unknown>>) => {
    if (error.response?.status === 401 || error.response?.data?.code === 1001) redirectToLogin()
    const fallback = error.code === 'ECONNABORTED' ? '请求超时，请先查看调用记录，再决定是否重试。'
      : !error.response ? '暂时无法连接服务，请检查网络后重试。'
      : error.response.status === 429 ? '操作较频繁，请稍后再试。' : '服务暂时不可用，请稍后重试。'
    return Promise.reject(failure(error.response?.data, fallback))
  },
)
export async function request<T>(config: AxiosRequestConfig): Promise<T> {
  const response = await apiClient.request<T>(config)
  return response.data
}
