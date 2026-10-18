import { MessageSquarePlus } from 'lucide-react'
import { ErrorNote, Loading } from '@/components/ui'
import { useConversation } from './useConversation'
import { SchemaForm } from './SchemaForm'
import { ConversationView } from './ConversationView'
import { ExecutionReceipt } from './ExecutionReceipt'
import type { MarketDetail } from './types'

export function ConversationPanel({ detail, executable, onBusy }: {
  detail: MarketDetail; executable: boolean; onBusy: (busy: boolean) => void
}) {
  const chat = useConversation(detail, onBusy)
  return (
    <div className="grid min-h-[640px] min-w-0 grid-cols-1 lg:grid-cols-[minmax(0,.7fr)_minmax(0,1.4fr)]">
      <aside className="min-w-0 space-y-6 border-b border-white/10 p-6 lg:border-b-0 lg:border-r">
        <div className="flex items-center justify-between">
          <h2 className="text-sm text-white/60">历史会话</h2>
          <button onClick={chat.startNew} disabled={chat.sending} className="flex items-center gap-2 text-xs text-[#c9f05b] disabled:opacity-40"><MessageSquarePlus size={14} />新建</button>
        </div>
        {chat.sessionsLoading && <Loading label="加载会话…" />}
        {chat.historyWarning && <p className="text-xs text-amber-200">{chat.historyWarning}</p>}
        {!chat.sessionsLoading && !chat.sessions.length && <p className="text-xs text-white/35">还没有会话，首次执行后会保存记录。</p>}
        <div className="max-h-[330px] space-y-2 overflow-y-auto">
          {chat.sessions.map((item) => (
            <button key={item.id} disabled={chat.sending} onClick={() => void chat.openSession(item.id)}
              className={`w-full rounded-xl px-3 py-3 text-left text-sm disabled:opacity-40 ${chat.sessionId === item.id ? 'bg-[#c9f05b] text-[#11130f]' : 'text-white/60 hover:bg-white/5'}`}>
              <span className="block truncate">{item.title || '新会话'}</span>
              <span className="mt-1 block text-[11px] opacity-60">{item.last_message_time || item.create_time}</span>
            </button>
          ))}
        </div>
        <p className="text-xs leading-6 text-white/35">历史仅属于当前账号。摘要每次新建记录；切换能力会开始新的输入上下文。</p>
        <details className="text-xs text-white/45">
          <summary className="cursor-pointer">查看参数 Schema</summary>
          <pre className="mt-3 max-h-64 overflow-auto whitespace-pre-wrap break-all text-[11px]">{JSON.stringify(detail.param_schema, null, 2)}</pre>
        </details>
      </aside>
      <div className="flex min-w-0 flex-col">
        <ConversationView bubbles={chat.bubbles} busy={chat.sending || chat.historyLoading} />
        {chat.receipt && <ExecutionReceipt receipt={chat.receipt} />}
        {chat.failure && <div className="space-y-2 px-6 pb-5"><ErrorNote message={chat.failure.message} />
          {chat.failure.requestId && <p className="break-all font-mono text-xs text-white/45">requestId: {chat.failure.requestId}</p>}
        </div>}
        <SchemaForm schema={detail.param_schema ?? {}} values={chat.values} onChange={chat.setValues}
          onSend={() => void chat.send()} sending={chat.sending} code={detail.code}
          disabled={!executable || chat.sending || chat.historyLoading} />
      </div>
    </div>
  )
}
