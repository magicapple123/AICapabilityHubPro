import { App } from 'antd'
import { Check, Copy } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

export function CopyButton({ text, label = '复制', compact = false }: { text: string; label?: string; compact?: boolean }) {
  const [copied, setCopied] = useState(false)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const { message } = App.useApp()
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current) }, [])
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      if (timer.current) clearTimeout(timer.current)
      timer.current = setTimeout(() => setCopied(false), 1800)
    } catch { void message.error('复制失败，请选中文本手动复制') }
  }
  return <button type="button" className="copy-button" aria-label={copied ? '已复制' : label} onClick={() => void copy()}>
    {copied ? <Check size={13} /> : <Copy size={13} />}{!compact && (copied ? '已复制' : label)}
  </button>
}
