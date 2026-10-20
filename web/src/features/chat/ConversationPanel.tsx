import { App } from 'antd'
import { ChevronDown, Code2, History, MessageSquare, Plus, Search } from 'lucide-react'
import { useEffect, useState } from 'react'
import { ErrorNote, Loading, Modal } from '@/components/ui'
import { CopyButton } from '@/components/CopyButton'
import { useConversation } from './useConversation'
import { usePendingNavigation } from './usePendingNavigation'
import { initialValues } from './schemaInput'
import { SchemaForm } from './SchemaForm'
import { ConversationView } from './ConversationView'
import { ExecutionReceipt } from './ExecutionReceipt'
import type { MarketDetail } from './types'

export function ConversationPanel({ detail, executable, onBusy }: {
  detail: MarketDetail; executable: boolean; onBusy: (busy: boolean) => void
}) {
  const chat = useConversation(detail, onBusy)
  const [historyOpen, setHistoryOpen] = useState(false)
  const [query, setQuery] = useState('')
  const { modal } = App.useApp()
  const baseline = chat.submittedValues ?? initialValues(detail.param_schema ?? {})
  const dirty = Object.keys(chat.values).some((name) => (chat.values[name] ?? '').trim() !== (baseline[name] ?? '').trim())
  const blocker = usePendingNavigation(chat.sending, dirty)
  useEffect(() => { if (chat.receipt) window.dispatchEvent(new Event('hub:balance-changed')) }, [chat.receipt])
  const start = () => {
    const reset = () => { chat.startNew(); chat.setValues(initialValues(detail.param_schema ?? {})) }
    if (dirty) modal.confirm({ title: '开始新的会话？', content: '当前尚未提交的输入将被清空。已有记录会保留在历史会话中。', okText: '新建会话', cancelText: '继续编辑', onOk: reset })
    else reset()
  }
  const open = (id: number) => {
    const apply = () => { void chat.openSession(id); setHistoryOpen(false) }
    if (dirty) modal.confirm({ title: '打开历史会话？', content: '当前输入将保留。发送时将使用选中会话作为上下文。', okText: '打开会话', cancelText: '继续编辑', onOk: apply })
    else apply()
  }
  const sessions = chat.sessions.filter((item) => item.title.toLowerCase().includes(query.toLowerCase()))
  return <div className="conversation-layout">
    <aside className={'chat-history' + (historyOpen ? ' history-open' : '')}>
      <div className="chat-history-heading"><button className="history-toggle" onClick={() => setHistoryOpen((value) => !value)}><History size={15} /><span>历史会话</span><ChevronDown size={13} /></button>
        <button className="icon-button" onClick={start} disabled={chat.sending} aria-label="新建会话"><Plus size={16} /></button></div>
      <div className="history-content"><label className="history-search"><Search size={13} /><input placeholder="搜索会话…" aria-label="搜索历史会话" value={query} onChange={(e) => setQuery(e.target.value)} /></label>
        {chat.sessionsLoading && <Loading label="读取会话…" />}
        {chat.historyWarning && <p className="history-warning">{chat.historyWarning}</p>}
        <div className="history-sessions">{sessions.map((item) => <button key={item.id} disabled={chat.sending || chat.historyLoading} onClick={() => open(item.id)}
          className={'history-session' + (chat.sessionId === item.id ? ' selected' : '')}><MessageSquare size={13} /><span><strong>{item.title || '新会话'}</strong><small>{(item.last_message_time || item.create_time).slice(0, 16)}</small></span></button>)}
          {!chat.sessionsLoading && !sessions.length && <p className="history-empty">{query ? '未找到匹配的会话' : '首次调用后，会话将在这里保存。'}</p>}</div>
        <div className="history-notes"><p>历史会话仅属于当前账号。文本摘要每次独立执行。</p><details><summary><Code2 size={12} />查看输入 Schema</summary><pre>{JSON.stringify(detail.param_schema, null, 2)}</pre></details></div>
      </div>
    </aside>
    <div className="conversation-main">
      <div className="conversation-topline"><span><span />{detail.code === 'long-summary' ? '文本摘要工作区' : '多轮对话工作区'}</span><span>{chat.sending ? '正在执行…' : chat.historyLoading ? '读取历史…' : '按能力计量'}</span></div>
      <ConversationView bubbles={chat.bubbles} busy={chat.sending || chat.historyLoading} code={detail.code}
        onExample={(text) => chat.setValues({ ...chat.values, [detail.code === 'long-summary' ? 'text' : 'messages']: text })} />
      {chat.receipt && <ExecutionReceipt receipt={chat.receipt} />}
      {chat.failure && <div className="chat-call-error"><ErrorNote message={chat.failure.message} />
        {chat.failure.requestId && <div className="chat-failure-id"><code>{chat.failure.requestId}</code><CopyButton text={chat.failure.requestId} label="复制 requestId" /></div>}</div>}
      <SchemaForm schema={detail.param_schema ?? {}} values={chat.values} onChange={chat.setValues}
        onSend={() => void chat.send()} sending={chat.sending} code={detail.code}
        disabled={!executable || chat.sending || chat.historyLoading} />
    </div>
    <Modal title={chat.sending ? '调用仍在执行，确认离开？' : '输入尚未提交，确认离开？'} open={blocker.state === 'blocked'}
      onClose={() => blocker.state === 'blocked' && blocker.reset()}
      footer={<div className="form-actions"><button className="button-secondary" onClick={() => blocker.state === 'blocked' && blocker.reset()}>留在当前页面</button><button className="button-primary" onClick={() => blocker.state === 'blocked' && blocker.proceed()}>确认离开</button></div>}>
      <p className="page-description">{chat.sending ? '离开页面不会取消服务端执行，调用仍可能产生费用。你可以稍后在调用记录中查看结果。' : '切换页面后，当前尚未发送的输入将不会保留。'}</p>
    </Modal>
  </div>
}
