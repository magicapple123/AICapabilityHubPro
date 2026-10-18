import { useEffect, useRef, useState } from 'react'
import { completeChat, fetchChatSessions, fetchSessionMessages } from '@/api/chat'
import type { ChatCompletionData, ChatSession } from '@/api/chat'
import { buildInput, initialValues } from './schemaInput'
import { callFailure } from './callFailure'
import type { Bubble, CallFailure, MarketDetail } from './types'

const WELCOME: Bubble = {
  key: 'welcome', role: 'assistant', context: false,
  content: '选择能力并填写输入。执行结果、实际积分和调用追踪会显示在这里。',
}

export function useConversation(detail: MarketDetail, onBusy: (busy: boolean) => void) {
  const [sessions, setSessions] = useState<ChatSession[]>([])
  const [sessionId, setSessionId] = useState<number | null>(null)
  const [bubbles, setBubbles] = useState<Bubble[]>([WELCOME])
  const [values, setValues] = useState(() => initialValues(detail.param_schema ?? {}))
  const [sending, setSending] = useState(false)
  const [historyLoading, setHistoryLoading] = useState(false)
  const [sessionsLoading, setSessionsLoading] = useState(true)
  const [failure, setFailure] = useState<CallFailure | null>(null)
  const [receipt, setReceipt] = useState<ChatCompletionData | null>(null)
  const [historyWarning, setHistoryWarning] = useState('')
  const generation = useRef(0)
  const active = useRef(true)
  const inFlight = useRef(false)

  useEffect(() => {
    active.current = true
    let ignore = false
    fetchChatSessions({ page: 1, page_size: 30 }).then((data) => {
      if (!ignore) setSessions(data.list)
    }).catch(() => {
      if (!ignore) setHistoryWarning('历史列表暂不可用，仍可新建调用。')
    }).finally(() => { if (!ignore) setSessionsLoading(false) })
    return () => { ignore = true; active.current = false }
  }, [])

  const startNew = () => {
    generation.current++
    setHistoryLoading(false)
    setSessionId(null)
    setBubbles([WELCOME])
    setFailure(null)
    setReceipt(null)
  }

  const openSession = async (id: number) => {
    const current = ++generation.current
    setHistoryLoading(true)
    setFailure(null)
    setReceipt(null)
    try {
      const data = await fetchSessionMessages(id)
      if (!active.current || current !== generation.current) return
      const items: Bubble[] = data.list.filter((item) => item.role !== 'system').map((item) => ({
        key: `message-${item.id}`, role: item.role === 'assistant' ? 'assistant' : 'user',
        content: item.content, context: true,
        meta: item.role === 'assistant' ? `${item.call_status === 'degraded' ? '降级 · ' : ''}${item.token_count} tokens` : undefined,
      }))
      setBubbles(items.length ? items : [WELCOME])
      setSessionId(id)
    } catch (cause) {
      if (active.current && current === generation.current) setFailure(callFailure(cause))
    } finally {
      if (active.current && current === generation.current) setHistoryLoading(false)
    }
  }

  const send = async () => {
    if (inFlight.current || historyLoading) return
    let input: Record<string, unknown>
    try { input = buildInput(detail.param_schema ?? {}, values, bubbles, detail.code) }
    catch (cause) { setFailure(callFailure(cause)); return }
    inFlight.current = true
    const content = typeof input.text === 'string' ? input.text
      : values.messages || JSON.stringify(input, null, 2)
    const before = bubbles
    const userBubble: Bubble = { key: `user-${Date.now()}`, role: 'user', content, context: true }
    setBubbles([...before, userBubble])
    setFailure(null)
    setReceipt(null)
    setSending(true)
    onBusy(true)
    try {
      const data = await completeChat({ capability_id: detail.id, input,
        session_id: detail.code === 'chat-completions' ? sessionId ?? undefined : undefined })
      if (!active.current) return
      setBubbles([...before, userBubble, {
        key: `assistant-${data.message_id}`, role: 'assistant', context: true,
        content: data.choices[0]?.message.content ?? '服务未返回内容。',
        meta: `${data.degraded ? '降级 · ' : data.mock ? '本地模拟 · ' : ''}${data.duration_ms} ms · ${data.cost} 积分`,
      }])
      setSessionId(data.session_id)
      setReceipt(data)
      setValues((previous) => ({ ...previous, messages: '' }))
      // A history refresh failure must never turn an already billed success into a retry.
      void fetchChatSessions({ page: 1, page_size: 30 }).then((history) => {
        if (active.current) setSessions(history.list)
      }).catch(() => { if (active.current) setHistoryWarning('本次调用已完成，历史列表刷新失败。') })
    } catch (cause) {
      if (active.current) { setBubbles(before); setFailure(callFailure(cause)) }
    } finally {
      inFlight.current = false
      if (active.current) setSending(false)
      onBusy(false)
    }
  }

  return { sessions, sessionId, bubbles, values, setValues, sending, historyLoading,
    sessionsLoading, failure, receipt, historyWarning, startNew, openSession, send }
}
