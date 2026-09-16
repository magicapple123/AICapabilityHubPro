import { request } from './client'
import type { PageData } from './types'

export type ChatRole = 'system' | 'user' | 'assistant'

export interface ChatMessagePayload {
  role: ChatRole
  content: string
}

export interface ChatCompletionPayload {
  /** 为空时新建会话；传入时必须是自己会话，否则返回 4004。 */
  session_id?: number
  model?: string
  messages: ChatMessagePayload[]
  temperature?: number
}

export interface ChatCompletionData {
  id: string
  object: string
  created: number
  model: string
  choices: Array<{
    index: number
    message: { role: string; content: string }
    finish_reason: string
  }>
  usage: { prompt_tokens: number; completion_tokens: number; total_tokens: number }
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
  request<ChatCompletionData>({ method: 'POST', url: '/chat/completions', data })

export const fetchChatSessions = (params: { page?: number; page_size?: number } = {}) =>
  request<PageData<ChatSession>>({ method: 'GET', url: '/chat/sessions', params })

export const fetchSessionMessages = (sessionId: number) =>
  request<{ list: ChatHistoryMessage[]; total: number }>({
    method: 'GET',
    url: `/chat/sessions/${sessionId}/messages`,
  })
