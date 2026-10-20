import { LoaderCircle } from 'lucide-react'
import { useEffect, useRef } from 'react'
import { CopyButton } from '@/components/CopyButton'
import { MessageContent } from './MessageContent'
import type { Bubble } from './types'

export function ConversationView({ bubbles, busy, code, onExample }: {
  bubbles: Bubble[]; busy: boolean; code: string; onExample: (text: string) => void
}) {
  const container = useRef<HTMLDivElement>(null)
  const stick = useRef(true)
  useEffect(() => {
    if (stick.current && container.current) container.current.scrollTo({
      top: container.current.scrollHeight, behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth',
    })
  }, [bubbles, busy])
  const empty = bubbles.every((bubble) => !bubble.context)
  const summary = code === 'long-summary'
  return <div ref={container} className="conversation-scroll" aria-live="polite" aria-busy={busy}
    onScroll={() => { const element = container.current; if (element) stick.current = element.scrollHeight - element.clientHeight - element.scrollTop < 90 }}>
    {empty && !busy ? <div className="chat-empty">
      <p className="chat-empty-label">{summary ? '文本摘要' : '新会话'}</p>
      <h2>{summary ? '输入需要处理的文本' : '从一条消息开始'}</h2><p>{summary ? '在下方粘贴原文。执行后可查看摘要和费用。' : '回复会显示在这里，并保存在你的会话记录中。'}</p>
      <div className="prompt-examples"><span>示例</span>{(summary ? [
        '人工智能正逐步融入教育、医疗和软件开发等领域。合理应用 AI 能够提高信息处理效率，但同时需要重视数据隐私、结果准确性与人工复核。建立清晰的使用规范和评价标准，有助于团队在保证质量的同时获得更高的协作效率。',
        '本周项目进展：已完成用户登录与能力目录联调，调试台支持聊天和文本摘要。下周计划：完善权限控制，补充异常场景测试，统一前端交互与文档。当前风险：内部目录接口仍需完成交接。',
      ] : ['用一个简单例子解释什么是 API', '帮我整理一份三周的项目学习计划', '写代码前，应该如何拆分任务？']).map((text, index) =>
        <button key={text} type="button" onClick={() => onExample(text)}>{summary ? ['试试：提炼文章要点', '试试：整理周报摘要'][index] : text}</button>)}</div>
    </div> : bubbles.filter((bubble) => bubble.context).map((bubble) => <article key={bubble.key} className={'message-row ' + (bubble.role === 'user' ? 'message-user' : 'message-assistant')}>
      <div className="message-body"><span className="message-author">{bubble.role === 'user' ? '你' : '助手'}</span>
        <div className="message-content"><MessageContent text={bubble.content} /></div><div className="message-meta">{bubble.meta && <span>{bubble.meta}</span>}
          {bubble.role === 'assistant' && <CopyButton text={bubble.content} label="复制回复" />}</div></div>
    </article>)}
    {busy && <div className="chat-thinking" role="status"><LoaderCircle size={15} className="spinner" /><span>正在处理…</span></div>}
  </div>
}
