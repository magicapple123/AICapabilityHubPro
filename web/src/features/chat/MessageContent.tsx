import { Fragment } from 'react'
import { CopyButton } from '@/components/CopyButton'

export function MessageContent({ text }: { text: string }) {
  const parts = []
  const fence = String.fromCharCode(96).repeat(3)
  const matches = text.matchAll(new RegExp(fence + '([\\w-]*)\\n([\\s\\S]*?)' + fence, 'g'))
  let previous = 0
  for (const match of matches) {
    const index = match.index
    if (index > previous) parts.push(<span key={'text-' + previous}>{text.slice(previous, index)}</span>)
    parts.push(<div className="message-code" key={'code-' + index}><div><span>{match[1] || '代码'}</span><CopyButton text={match[2]} label="复制代码" /></div><pre><code>{match[2]}</code></pre></div>)
    previous = index + match[0].length
  }
  if (previous < text.length) parts.push(<span key={'text-' + previous}>{text.slice(previous)}</span>)
  return <>{parts.map((part, index) => <Fragment key={index}>{part}</Fragment>)}</>
}
