import { CheckCheck, ReceiptText } from 'lucide-react'
import type { ChatCompletionData } from '@/api/chat'
import { CopyButton } from '@/components/CopyButton'
import { StatusTag } from '@/components/ui'

const BILLING_MODE_LABELS: Record<string, string> = {
  per_call: '按次',
  per_token: '按 token',
  per_unit: '按件',
}

/** 计费口径：模式 + 对应单价，和实际消耗分开展示，避免"单价=扣费"的误读。 */
function priceOf(receipt: ChatCompletionData, mode: string): string {
  if (mode === 'per_token') {
    return `输入 ${receipt.price_per_1k_input ?? 0} / 输出 ${receipt.price_per_1k_output ?? 0} 积分每 1k tokens`
  }
  if (mode === 'per_unit') {
    return `${receipt.price_per_unit ?? 0} 积分 / ${receipt.unit || '件'}`
  }
  return `${receipt.price_per_call ?? 0} 积分 / 次`
}

export function ExecutionReceipt({ receipt }: { receipt: ChatCompletionData }) {
  // C1：token 只认上游 usage；missing 时必须明说，不能用 0 冒充"没消耗"。
  const mode = receipt.billing_mode || 'per_call'
  const missing = receipt.usage_source === 'missing'
  const estimated = receipt.usage_source === 'mock'
  const promptTokens = receipt.prompt_tokens ?? receipt.usage.prompt_tokens
  const completionTokens = receipt.completion_tokens ?? receipt.usage.completion_tokens
  const totalTokens = receipt.total_tokens ?? receipt.usage.total_tokens
  return <details className="execution-receipt" open>
    <summary><ReceiptText size={14} /><strong>执行收据</strong><StatusTag value={receipt.call_status} /><span>{receipt.mock ? '本地模拟' : '模型执行'}</span></summary>
    <div className="receipt-metrics">
      <span>实际消耗<b>{receipt.cost} 积分</b></span>
      <span>计费模式<b>{BILLING_MODE_LABELS[mode] ?? mode}</b></span>
      <span>登记单价<b>{priceOf(receipt, mode)}</b></span>
      <span>执行耗时<b>{receipt.duration_ms} ms</b></span>
    </div>
    <div className="receipt-metrics">
      {missing
        ? <span>用量<b>上游未返回用量</b></span>
        : <span>用量（tokens）<b>输入 {promptTokens} / 输出 {completionTokens} / 合计 {totalTokens}</b></span>}
      {estimated && <span className="muted">Mock 估算值，非上游真值</span>}
    </div>
    <div className="receipt-bottom"><span><CheckCheck size={12} />{receipt.billing_status === 'recorded' ? '账单 #' + receipt.record_id : '当前未记账'} · 能力 #{receipt.capability_id}</span>
      {receipt.degraded && <span>降级码 {receipt.error_code} · 未扣费</span>}</div>
    <div className="receipt-trace"><code>requestId: {receipt.request_id}</code><CopyButton text={receipt.request_id} label="复制 requestId" /></div>
  </details>
}
