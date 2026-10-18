import { useState } from 'react'
import { ErrorNote, Loading } from '@/components/ui'
import { ConversationPanel } from './ConversationPanel'
import { useCapabilityCatalog } from './useCapabilityCatalog'
import { objectValue } from './schemaInput'

export function ChatWorkspace() {
  const catalog = useCapabilityCatalog()
  const [busy, setBusy] = useState(false)
  const detail = catalog.detail
  const executable = !!detail && !!catalog.executors?.codes.includes(detail.code)
    && objectValue(detail.param_schema) && detail.param_schema.type === 'object'
  return (
    <div className="mt-12 overflow-hidden rounded-[2rem] border border-white/10 bg-[#181c17]">
      <div className="flex flex-wrap items-end justify-between gap-6 border-b border-white/10 p-6 md:p-8">
        <label className="block min-w-0 flex-1 text-xs text-white/50">调用能力
          <select aria-label="调用能力" disabled={busy || catalog.loading}
            value={catalog.id?.toString() ?? ''} onChange={(event) => catalog.select(event.target.value)}
            className="mt-2 w-full max-w-xl rounded-xl border border-white/20 bg-[#11130f] px-4 py-3 text-base text-white disabled:opacity-50">
            {!catalog.list.some((item) => item.id === catalog.id) && <option value={catalog.id?.toString() ?? ''}>所选能力不可用</option>}
            {catalog.list.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.price_per_call} 积分</option>)}
          </select>
        </label>
        {detail && <div className="text-right"><p className="text-2xl text-[#c9f05b]">{detail.price_per_call}<span className="ml-2 text-xs text-white/50">积分 / 次</span></p>
          <p className="mt-2 text-xs text-white/40">能力 #{detail.id} · {detail.code}</p></div>}
      </div>
      {catalog.loading && <div className="p-8"><Loading label="读取能力详情与执行器…" /></div>}
      {catalog.error && <div className="p-6"><ErrorNote message={catalog.error} onRetry={catalog.retry} /></div>}
      {detail && !catalog.loading && <>
        <div className="space-y-2 border-b border-white/10 px-6 py-4 text-sm text-white/50">
          <p>{detail.description}</p>
          {!executable && <p className="text-amber-200">该能力暂无兼容执行器或参数 Schema，当前不可体验。请选择聊天或文本摘要。</p>}
          {catalog.executors?.catalog_mode === 'market' && <p className="text-xs text-white/35">本地联调使用旧市场的已上架详情；内部目录接口就绪后可切回正式集成模式。</p>}
        </div>
        <ConversationPanel key={detail.id} detail={detail} executable={executable} onBusy={setBusy} />
      </>}
    </div>
  )
}
