import { Bot, Copy, LoaderCircle, MessageSquarePlus, Send, UserRound } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'

import { completeChat, fetchChatSessions, fetchSessionMessages } from '@/api/chat'
import type { ChatSession } from '@/api/chat'
import { EmptyNote, ErrorNote, Loading } from '@/components/ui'

interface Bubble {
  key: string
  role: 'user' | 'assistant'
  content: string
  /** 助手消息的执行状态说明（Mock / 降级 / 耗时）。 */
  meta?: string
}

const WELCOME: Bubble = {
  key: 'welcome',
  role: 'assistant',
  content: '你好，我是能力调试助手。发一条消息，看看它如何被转成可复用的调用。',
}

/** 上下文最多带最近 20 条，避免一次请求体过大。 */
const MAX_CONTEXT_MESSAGES = 20

export function ChatPage() {
  const [sessions, setSessions] = useState<ChatSession[]>([])
  const [sessionId, setSessionId] = useState<number | null>(null)
  const [bubbles, setBubbles] = useState<Bubble[]>([WELCOME])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [sessionsLoading, setSessionsLoading] = useState(true)
  const [historyLoading, setHistoryLoading] = useState(false)
  const [error, setError] = useState('')

  const openSession = useCallback(async (id: number) => {
    setHistoryLoading(true)
    setError('')
    try {
      const data = await fetchSessionMessages(id)
      const items: Bubble[] = data.list.map((item) => ({
        key: `msg-${item.id}`,
        role: item.role === 'assistant' ? 'assistant' : 'user',
        content: item.content,
        meta:
          item.role === 'assistant'
            ? `${item.call_status === 'degraded' ? '降级 · ' : ''}${item.token_count} tokens`
            : undefined,
      }))
      setBubbles(items.length > 0 ? items : [WELCOME])
      setSessionId(id)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '会话消息加载失败')
    } finally {
      setHistoryLoading(false)
    }
  }, [])

  const loadSessions = useCallback(
    async (autoOpen: boolean) => {
      setSessionsLoading(true)
      try {
        const data = await fetchChatSessions({ page: 1, page_size: 30 })
        const list = data.list ?? []
        setSessions(list)
        if (autoOpen && list.length > 0) await openSession(list[0].id)
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : '会话列表加载失败')
      } finally {
        setSessionsLoading(false)
      }
    },
    [openSession],
  )

  useEffect(() => {
    void loadSessions(true)
  }, [loadSessions])

  const startNewSession = () => {
    setSessionId(null)
    setBubbles([WELCOME])
    setError('')
  }

  const send = async () => {
    const text = input.trim()
    if (!text || sending) return
    setInput('')
    setError('')

    const userBubble: Bubble = { key: `local-${Date.now()}`, role: 'user', content: text }
    const nextBubbles = [...bubbles, userBubble]
    setBubbles(nextBubbles)
    setSending(true)

    try {
      // 带上历史上下文，服务端会落库本轮的用户消息与助手回复。
      const context = nextBubbles
        .filter((item) => item.role === 'user' || item.role === 'assistant')
        .slice(-MAX_CONTEXT_MESSAGES)
        .map((item) => ({ role: item.role, content: item.content }))

      const data = await completeChat({
        session_id: sessionId ?? undefined,
        model: 'mock-model',
        messages: context,
      })

      const answer = data.choices?.[0]?.message?.content ?? '能力已收到请求，但未返回内容。'
      const meta = data.degraded
        ? `降级（${data.error_code}） · 本次未计费`
        : `${data.mock ? 'Mock · ' : ''}${data.duration_ms} ms · ${data.usage.total_tokens} tokens`

      setBubbles((items) => [
        ...items,
        { key: `assistant-${data.message_id}`, role: 'assistant', content: answer, meta },
      ])
      setSessionId(data.session_id)
      await loadSessions(false)
    } catch (cause) {
      // 积分不足（3001）、能力下架、限流等都在这里统一提示。
      setError(cause instanceof Error ? cause.message : '调用失败，请稍后重试')
      setBubbles((items) => items.filter((item) => item.key !== userBubble.key))
      setInput(text)
    } finally {
      setSending(false)
    }
  }

  return (
    <section className="mx-auto max-w-[1500px] px-5 pb-32 pt-12 md:px-10 md:pt-20">
      <div className="flex items-end justify-between gap-8">
        <div>
          <p className="mb-5 text-sm text-[#c9f05b]">在线调试台</p>
          <h1 className="max-w-5xl text-5xl font-medium leading-[.95] tracking-[-.07em] text-[#f4f4ef] md:text-7xl">
            让一次调用
            <br />
            <span className="text-white/35">变得可见。</span>
          </h1>
        </div>
        <span className="hidden items-center gap-2 text-xs uppercase tracking-[.2em] text-white/35 md:flex">
          <span className="h-2 w-2 rounded-full bg-[#c9f05b]" /> ai-chat-service
        </span>
      </div>

      <div className="mt-16 grid min-h-[640px] overflow-hidden rounded-[2rem] border border-white/10 bg-[#181c17] lg:grid-cols-[.8fr_1.4fr]">
        <aside className="border-b border-white/10 p-7 lg:border-b-0 lg:border-r md:p-8">
          <div className="flex items-center justify-between">
            <p className="text-xs uppercase tracking-[.2em] text-white/35">会话</p>
            <button
              onClick={startNewSession}
              className="flex items-center gap-2 text-xs text-[#c9f05b] hover:text-white"
            >
              <MessageSquarePlus size={14} /> 新建对话
            </button>
          </div>

          <div className="mt-6 max-h-[300px] space-y-2 overflow-y-auto pr-1">
            {sessionsLoading && <Loading label="加载会话…" />}
            {!sessionsLoading && sessions.length === 0 && (
              <EmptyNote message="还没有会话，发送第一条消息即会创建。" />
            )}
            {!sessionsLoading &&
              sessions.map((item) => (
                <button
                  key={item.id}
                  onClick={() => void openSession(item.id)}
                  className={`w-full rounded-xl px-4 py-3 text-left text-sm transition ${
                    sessionId === item.id
                      ? 'bg-[#c9f05b] text-[#11130f]'
                      : 'text-white/60 hover:bg-white/5 hover:text-white'
                  }`}
                >
                  <span className="block truncate">{item.title || '新对话'}</span>
                  <span
                    className={`mt-1 block text-[11px] ${
                      sessionId === item.id ? 'text-[#11130f]/60' : 'text-white/30'
                    }`}
                  >
                    {item.last_message_time ?? item.create_time}
                  </span>
                </button>
              ))}
          </div>

          <div className="mt-8 space-y-3 text-sm text-white/55">
            <div className="flex justify-between border-b border-white/10 pb-3">
              <span>服务</span>
              <span className="text-white">ai-chat-service</span>
            </div>
            <div className="flex justify-between border-b border-white/10 pb-3">
              <span>模型</span>
              <span className="text-white">mock-model</span>
            </div>
            <div className="flex justify-between border-b border-white/10 pb-3">
              <span>计费</span>
              <span className="text-white">按次扣积分</span>
            </div>
          </div>
          <p className="mt-6 text-xs leading-5 text-white/30">
            对话会写入会话与消息表；真实模型超时会自动降级且不计费。
          </p>
        </aside>

        <div className="flex min-h-[640px] flex-col">
          <div className="flex-1 space-y-5 overflow-y-auto p-7 md:p-9">
            {historyLoading && <Loading label="加载历史消息…" />}
            {!historyLoading &&
              bubbles.map((bubble) => (
                <div
                  key={bubble.key}
                  className={`flex gap-4 ${bubble.role === 'user' ? 'justify-end' : ''}`}
                >
                  <div
                    className={`flex max-w-[80%] gap-3 ${
                      bubble.role === 'user' ? 'flex-row-reverse' : ''
                    }`}
                  >
                    <span
                      className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full ${
                        bubble.role === 'user'
                          ? 'bg-white text-[#11130f]'
                          : 'bg-[#c9f05b] text-[#11130f]'
                      }`}
                    >
                      {bubble.role === 'user' ? <UserRound size={15} /> : <Bot size={15} />}
                    </span>
                    <div>
                      <div
                        className={`rounded-2xl px-4 py-3 text-sm leading-6 ${
                          bubble.role === 'user'
                            ? 'bg-white text-[#11130f]'
                            : 'bg-white/5 text-white/75'
                        }`}
                      >
                        {bubble.content}
                        {bubble.role === 'assistant' && (
                          <button
                            className="ml-3 text-white/35 hover:text-[#c9f05b]"
                            onClick={() => void navigator.clipboard?.writeText(bubble.content)}
                            aria-label="复制回复"
                          >
                            <Copy size={13} className="inline" />
                          </button>
                        )}
                      </div>
                      {bubble.meta && (
                        <p className="mt-2 text-[11px] text-white/30">{bubble.meta}</p>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            {sending && (
              <div className="flex items-center gap-2 text-xs text-white/35">
                <LoaderCircle size={14} className="animate-spin" /> 能力正在响应…
              </div>
            )}
          </div>

          {error && (
            <div className="px-5 md:px-7">
              <ErrorNote message={error} />
            </div>
          )}

          <div className="border-t border-white/10 p-5 md:p-7">
            <div className="flex items-center gap-3 rounded-2xl border border-white/15 bg-[#11130f] p-2 focus-within:border-[#c9f05b]">
              <input
                value={input}
                onChange={(event) => setInput(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') void send()
                }}
                placeholder="输入一条测试消息…"
                className="min-w-0 flex-1 bg-transparent px-3 py-3 text-sm text-white outline-none placeholder:text-white/25"
              />
              <button
                onClick={() => void send()}
                disabled={sending}
                className="flex h-11 w-11 items-center justify-center rounded-xl bg-[#c9f05b] text-[#11130f] transition hover:bg-white disabled:opacity-50"
                aria-label="发送"
              >
                <Send size={17} />
              </button>
            </div>
            <p className="mt-3 text-[11px] text-white/25">
              请求经 Gateway → ai-chat-service，自动携带 JWT 与 requestId；积分不足会返回 3001。
            </p>
          </div>
        </div>
      </div>
    </section>
  )
}
