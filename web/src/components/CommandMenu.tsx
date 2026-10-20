import { ArrowRight, Search } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Modal } from './ui'
import { navigationLinks } from './navigation'

export function CommandMenu({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [query, setQuery] = useState('')
  const [selected, setSelected] = useState(0)
  const input = useRef<HTMLInputElement>(null)
  const navigate = useNavigate()
  const matches = navigationLinks.filter((item) => (item.label + item.description).includes(query.trim()))
  useEffect(() => {
    if (!open) return
    setQuery('')
    setSelected(0)
    const id = window.setTimeout(() => input.current?.focus(), 100)
    return () => window.clearTimeout(id)
  }, [open])
  const go = (href: string) => { onClose(); navigate(href) }
  return <Modal title="快速前往" open={open} onClose={onClose}>
    <div className="command-input"><Search size={17} /><input ref={input} value={query} aria-label="搜索页面或功能"
      placeholder="搜索页面或功能…" onChange={(e) => { setQuery(e.target.value); setSelected(0) }}
      role="combobox" aria-expanded="true" aria-controls="command-results" aria-activedescendant={matches.length ? 'command-' + selected : undefined}
      onKeyDown={(e) => {
        if (e.key === 'ArrowDown') { e.preventDefault(); setSelected((n) => Math.min(n + 1, matches.length - 1)) }
        if (e.key === 'ArrowUp') { e.preventDefault(); setSelected((n) => Math.max(n - 1, 0)) }
        if (e.key === 'Enter' && matches[selected]) { e.preventDefault(); go(matches[selected].href) }
      }} /></div>
    <div className="command-results" id="command-results" role="listbox" aria-label="页面搜索结果">
      {matches.map((item, index) => <button id={'command-' + index} role="option" aria-selected={selected === index}
        key={item.href} className={'command-option' + (selected === index ? ' selected' : '')}
        onMouseEnter={() => setSelected(index)} onClick={() => go(item.href)}>
        <item.icon size={18} /><span><strong>{item.label}</strong><small>{item.description}</small></span><ArrowRight size={15} />
      </button>)}
      {!matches.length && <p className="command-empty">没有找到相关页面，试试“调试”或“积分”。</p>}
    </div>
    <p className="command-hint">↑ ↓ 选择 · Enter 前往 · Esc 关闭</p>
  </Modal>
}
