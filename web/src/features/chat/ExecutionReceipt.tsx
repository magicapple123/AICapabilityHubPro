import { CheckCheck, ReceiptText } from 'lucide-react'
import type { ChatCompletionData } from '@/api/chat'
import { CopyButton } from '@/components/CopyButton'
import { StatusTag } from '@/components/ui'

export function ExecutionReceipt({ receipt }: { receipt: ChatCompletionData }) {
  return <details className="execution-receipt" open>
    <summary><ReceiptText size={14} /><strong>执行收据</strong><StatusTag value={receipt.call_status} /><span>{receipt.mock ? '本地模拟' : '模型执行'}</span></summary>
    <div className="receipt-metrics"><span>实际消耗<b>{receipt.cost} 积分</b></span><span>登记单价<b>{receipt.price_per_call} 积分</b></span><span>执行耗时<b>{receipt.duration_ms} ms</b></span><span>使用量<b>{receipt.usage.total_tokens} tokens</b></span></div>
    <div className="receipt-bottom"><span><CheckCheck size={12} />{receipt.billing_status === 'recorded' ? '账单 #' + receipt.record_id : '当前未记账'} · 能力 #{receipt.capability_id}</span>
      {receipt.degraded && <span>降级码 {receipt.error_code} · 未扣费</span>}</div>
    <div className="receipt-trace"><code>requestId: {receipt.request_id}</code><CopyButton text={receipt.request_id} label="复制 requestId" /></div>
  </details>
}
