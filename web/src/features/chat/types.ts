import type { MarketCapability } from '@/api/capability'

export interface MarketDetail extends MarketCapability {
  param_schema: Record<string, unknown> | null
}

export interface ExecutorCatalog {
  codes: string[]
  input_schemas: Record<string, unknown>
  catalog_mode: 'internal' | 'market'
}

export interface Bubble {
  key: string
  role: 'user' | 'assistant'
  content: string
  meta?: string
  /** Only actual conversation turns belong to the context. */
  context: boolean
}

export type FormValues = Record<string, string>

export interface CallFailure {
  message: string
  requestId?: string
}
