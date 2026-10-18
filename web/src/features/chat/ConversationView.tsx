import { Bot, Copy, LoaderCircle, UserRound } from 'lucide-react'
import type { Bubble } from './types'

export function ConversationView({ bubbles, busy }: { bubbles: Bubble[]; busy: boolean }) {
  return (
    <div className="max-h-[640px] min-h-[280px] flex-1 space-y-6 overflow-y-auto p-6 md:p-9" aria-live="polite" aria-busy={busy}>
      {bubbles.map((bubble) => (
        <div key={bubble.key} className={`flex gap-3 ${bubble.role === 'user' ? 'flex-row-reverse' : ''}`}>
          <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full ${bubble.role === 'user' ? 'bg-white text-[#11130f]' : 'bg-[#c9f05b] text-[#11130f]'}`}>
            {bubble.role === 'user' ? <UserRound size={15} /> : <Bot size={15} />}
          </span>
          <div className="max-w-[88%]">
            <div className="whitespace-pre-wrap break-words rounded-2xl bg-white/5 px-4 py-3 text-sm leading-7 text-white/80">
              {bubble.content}
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-white/40">
              {bubble.meta && <span>{bubble.meta}</span>}
              {bubble.role === 'assistant' && bubble.context && (
                <button type="button" aria-label="复制回复" onClick={() => { void navigator.clipboard?.writeText(bubble.content).catch(() => undefined) }} className="hover:text-[#c9f05b]">
                  <Copy size={13} />
                </button>
              )}
            </div>
          </div>
        </div>
      ))}
      {busy && <p className="flex items-center gap-2 text-sm text-white/40"><LoaderCircle size={15} className="animate-spin" />正在处理…</p>}
    </div>
  )
}
