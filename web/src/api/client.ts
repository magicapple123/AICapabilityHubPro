import axios, { AxiosError, type AxiosRequestConfig } from 'axios'
import type { Result } from './types'
import { env } from '@/utils/env'
import { useAuthStore } from '@/stores/auth'

// baseURL 已包含 /api 前缀。调用方传 url 时只写网关路由之后的剩余路径，
// 例如 request({ url: '/capability/market' })；写成 '/api/xxx' 会被拼成
// /api/api/xxx 而 404。
export const apiClient = axios.create({
  baseURL: env.apiBaseUrl,
  timeout: 15_000,
  headers: { 'Content-Type': 'application/json' },
})

const redirectToLogin = () => {
  useAuthStore.getState().clearAuth()
  if (window.location.pathname !== '/login') window.location.assign('/login')
}

apiClient.interceptors.request.use((config) => {
  const token = useAuthStore.getState().token
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

apiClient.interceptors.response.use(
  (response) => {
    const body = response.data as Result<unknown> | undefined
    if (body && typeof body.code === 'number') {
      if (body.code !== 0) {
        if (body.code === 1001) redirectToLogin()
        const error = new Error(body.message || '请求失败') as Error & { result?: Result<unknown> }
        error.result = body
        return Promise.reject(error)
      }
      response.data = body.data
    }
    return response
  },
  (error: AxiosError<Result<unknown>>) => {
    if (error.response?.status === 401 || error.response?.data?.code === 1001) {
      redirectToLogin()
    }
    return Promise.reject(error)
  },
)

export const request = async <T>(config: AxiosRequestConfig): Promise<T> => {
  const response = await apiClient.request<T>(config)
  return response.data
}
