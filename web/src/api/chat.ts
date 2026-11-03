import { request } from './client'
import type { PageData } from './types'

export type ChatRole = 'system' | 'user' | 'assistant'

export interface ChatMessagePayload {
  role: ChatRole
  content: string
}

export interface ChatCompletionPayload {
  capability_id?: number
  input?: Record<string, unknown>
  /** 为空时新建会话；传入时必须是自己会话，否则返回 4004。 */
  session_id?: number
  model?: string
  messages?: ChatMessagePayload[]
  temperature?: number
}

export type BillingMode = 'per_call' | 'per_token' | 'per_unit'

/** D3：文生图产物；`revised_prompt` 是上游改写后的提示词（部分供应商不返回）。 */
export interface GeneratedImage {
  url: string
  revised_prompt?: string
}

export interface ChatCompletionData {
  capability_id: number
  capability_code: string
  price_per_call: number
  cost: number
  request_id: string
  record_id: number | null
  billing_status: 'recorded' | 'not_reported'
  catalog_source: 'internal' | 'market'
  id: string
  object: string
  created: number
  model: string
  choices: Array<{
    index: number
    message: { role: string; content: string; tool_calls?: unknown[] }
    finish_reason: string
    /** D3：OpenAI 风格的图片产物（与顶层 images 内容一致）。 */
    images?: GeneratedImage[]
  }>
  usage: { prompt_tokens: number; completion_tokens: number; total_tokens: number }
  /** C2：顶层 token 明细，收据可直接展示"输入/输出/合计"。 */
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  /** C1：上游真值 / Mock 估算 / 上游未返回。 */
  usage_source: 'upstream' | 'mock' | 'missing'
  /** C2：本次调用采用的计价模式与对应单价。 */
  billing_mode: BillingMode
  price_per_1k_input: number
  price_per_1k_output: number
  price_per_unit: number
  unit: string
  /** D3：文生图结果；文本能力为空数组。 */
  images?: GeneratedImage[]
  session_id: number
  message_id: number
  mock: boolean
  call_status: 'success' | 'degraded' | 'failed'
  /** 降级时为 true（模型超时 5001 / 返回异常 5002），此时不扣积分。 */
  degraded: boolean
  error_code: number | null
  duration_ms: number
}

export interface ChatSession {
  id: number
  title: string
  last_message_time: string | null
  create_time: string
  update_time: string
}

export interface ChatHistoryMessage {
  id: number
  session_id: number
  role: ChatRole
  content: string
  call_status: string
  token_count: number
  create_time: string
}

export const completeChat = (data: ChatCompletionPayload) =>
  request<ChatCompletionData>({ method: 'POST', url: '/chat/completions', data, timeout: 90_000 })

export const fetchChatSessions = (params: { page?: number; page_size?: number } = {}) =>
  request<PageData<ChatSession>>({ method: 'GET', url: '/chat/sessions', params })

export const fetchSessionMessages = (sessionId: number) =>
  request<{ list: ChatHistoryMessage[]; total: number }>({
    method: 'GET',
    url: `/chat/sessions/${sessionId}/messages`,
  })
