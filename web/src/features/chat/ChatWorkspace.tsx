import { Coins, FlaskConical, Info } from 'lucide-react'
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
  return <div className="chat-workspace">
    <div className="chat-workspace-toolbar"><span className="workspace-tool-icon"><FlaskConical size={20} /></span>
      <label className="chat-capability-label"><span>当前调用能力</span><select aria-label="调用能力" disabled={busy || catalog.loading}
        value={catalog.id?.toString() ?? ''} onChange={(e) => catalog.select(e.target.value)}>
        {!catalog.list.some((item) => item.id === catalog.id) && <option value={catalog.id?.toString() ?? ''}>请选择可用能力</option>}
        {catalog.list.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
      </select></label>
      {detail && <><span className="chat-capability-code">{detail.code}</span><div className="chat-price"><Coins size={15} /><strong>{detail.price_per_call}</strong><span>积分 / 次</span></div></>}
    </div>
    {catalog.loading && <Loading label="正在读取能力与输入要求…" />}
    {catalog.error && <div className="p-6"><ErrorNote message={catalog.error} onRetry={catalog.retry} /></div>}
    {detail && !catalog.loading && <>
      <div className="chat-capability-description"><Info size={13} /><span>{detail.description || '按照输入要求填写，服务端会在执行前再次校验。'}</span>
        {!executable && <strong>暂无兼容执行器或输入要求，请选择其他能力。</strong>}</div>
      <ConversationPanel key={detail.id} detail={detail} executable={!!executable} onBusy={setBusy} />
    </>}
  </div>
}
