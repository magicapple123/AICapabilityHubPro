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
