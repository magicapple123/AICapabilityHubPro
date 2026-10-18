import { isAxiosError } from 'axios'
import { objectValue } from './schemaInput'
import type { CallFailure } from './types'

export function callFailure(cause: unknown): CallFailure {
  const body: unknown = isAxiosError(cause) ? cause.response?.data
    : cause instanceof Error && 'result' in cause ? cause.result : null
  const result = objectValue(body) ? body : {}
  return {
    message: typeof result.message === 'string' ? result.message
      : cause instanceof Error ? cause.message : '调用失败，请稍后重试。',
    requestId: typeof result.requestId === 'string' ? result.requestId : undefined,
  }
}
