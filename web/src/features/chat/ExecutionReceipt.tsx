import { Copy } from 'lucide-react'
import type { ChatCompletionData } from '@/api/chat'
import { StatusTag } from '@/components/ui'

export function ExecutionReceipt({ receipt }: { receipt: ChatCompletionData }) {
  return (
    <div className="mx-6 mb-6 space-y-3 rounded-xl border border-[#c9f05b]/20 bg-[#c9f05b]/5 p-4 text-xs text-white/65" role="status">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <span>{receipt.capability_code} · #{receipt.capability_id}</span>
        <StatusTag value={receipt.call_status} />
      </div>
      <p>登记单价 {receipt.price_per_call} 积分 · 本次 {receipt.cost} 积分 · {receipt.duration_ms} ms</p>
      <p>{receipt.mock ? '本地模拟执行' : '模型执行'}{receipt.degraded ? ` · 降级码 ${receipt.error_code}` : ''}
        {receipt.billing_status === 'not_reported' ? ' · 联调已关闭记账，请勿视作计费验收' : ` · 账单 #${receipt.record_id}`}</p>
      <div className="flex items-center gap-2 break-all font-mono">
        <span>requestId: {receipt.request_id}</span>
        <button type="button" aria-label="复制 requestId" onClick={() => { void navigator.clipboard?.writeText(receipt.request_id).catch(() => undefined) }}><Copy size={13} /></button>
      </div>
    </div>
  )
}
