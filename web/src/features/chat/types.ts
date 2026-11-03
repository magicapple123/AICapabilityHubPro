import type { MarketCapability } from '@/api/capability'
import type { GeneratedImage } from '@/api/chat'

export interface MarketDetail extends MarketCapability {
  param_schema: Record<string, unknown> | null
}

export interface ExecutorCatalog {
  codes: string[]
  /** D2：已接入执行器名（与 codes 同源，市场"暂无执行器"以它为准）。 */
  executors?: string[]
  input_schemas: Record<string, unknown>
  catalog_mode: 'internal' | 'market'
}

export interface Bubble {
  key: string
  role: 'user' | 'assistant'
  content: string
  meta?: string
  /** D3：文生图产物，仅当次执行有图片时存在。 */
  images?: GeneratedImage[]
  /** Only actual conversation turns belong to the context. */
  context: boolean
}

export type FormValues = Record<string, string>

export interface CallFailure {
  message: string
  requestId?: string
}
