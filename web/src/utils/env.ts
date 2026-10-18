const asBoolean = (value: string | undefined, fallback: boolean): boolean => {
  if (value === undefined) return fallback
  return ['true', '1', 'yes', 'on'].includes(value.toLowerCase())
}

export const env = {
  // 开发由 Vite 代理 /api，生产由 Nginx 代理 /api，统一使用同源路径。
  apiBaseUrl: import.meta.env.VITE_API_BASE_URL || '/api',
  // Pro 默认走真实 user-service 登录；仅在本地明确配置 true 时启用占位登录。
  useMockLogin: asBoolean(import.meta.env.VITE_USE_MOCK_LOGIN, false),
  devToken: import.meta.env.VITE_DEV_TOKEN || '',
}
