import { request } from './client'

/** 与 docs/api-contract/ai-chat-service.md 第 10 节一致；响应只含掩码。 */
export interface ModelProvider {
  id: number
  name: string
  alias: string
  protocol: string
  base_url: string
  api_key_mask: string
  default_model: string
  timeout_ms: number
  status: 'draft' | 'enabled' | 'disabled'
  last_test_ok_at: string | null
  create_time: string
  update_time: string
}

export const fetchProviders = () =>
  request<{ list: ModelProvider[]; total: number }>({ method: 'GET', url: '/chat/providers' })

export const testProvider = (id: number) =>
  request<{ provider_id: number; ok: boolean; reason: string; http_status: number | null; elapsed_ms: number }>(
    { method: 'POST', url: `/chat/providers/${id}/test` },
  )

/** 写入体：编辑时不传 api_key 表示保持原密钥不变。 */
export interface ProviderPayload {
  name: string
  alias: string
  protocol: 'openai-chat' | 'openai-image' | 'openai-embedding' | 'dashscope-image' | 'openai-responses' | 'custom-http'
  base_url: string
  api_key?: string
  default_model: string
  timeout_ms: number
}

/**
 * 编辑写入体。
 *
 * 后端 `ProviderUpdateRequest` 是 `extra="forbid"`，且**不含** alias / protocol
 * （两者创建后不可变）。多传任何一个字段都会被判为多余字段并返回 422 → code 2001，
 * 因此这里用 Omit 在类型层面禁止携带 alias / protocol。
 */
export type ProviderUpdatePayload = Omit<ProviderPayload, 'alias' | 'protocol'>

export const createProvider = (payload: ProviderPayload) =>
  request<ModelProvider>({ method: 'POST', url: '/chat/providers', data: payload })

export const updateProvider = (id: number, payload: ProviderUpdatePayload) =>
  request<ModelProvider>({ method: 'PUT', url: `/chat/providers/${id}`, data: payload })

export const setProviderStatus = (id: number, status: 'enabled' | 'disabled') =>
  request<ModelProvider>({ method: 'PUT', url: `/chat/providers/${id}/status`, data: { status } })
