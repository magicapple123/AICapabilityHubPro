import { Button } from 'antd'
import { ArrowUpRight, LogOut, Menu, X } from 'lucide-react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useState } from 'react'
import { useAuthStore } from '@/stores/auth'
import { MockNotice } from '@/components/ui'
import { BrandMark } from './BrandMark'

export function AppShell() {
  const location = useLocation()
  const navigate = useNavigate()
  const { userName, clearAuth } = useAuthStore()
  const [menuOpen, setMenuOpen] = useState(false)
  const links = [
    { href: '/', label: '工作台' },
    { href: '/capabilities', label: '能力市场' },
    { href: '/chat', label: '在线调试' },
    { href: '/usage', label: '调用记录' },
    { href: '/console', label: '运营后台' },
  ]

  // 根路径精确匹配，其余按前缀匹配，避免 /settings 等页面无法高亮。
  const isActive = (href: string) =>
    href === '/' ? location.pathname === '/' : location.pathname.startsWith(href)

  return (
    <div className="min-h-screen bg-[#11130f] text-[#f4f4ef]">
      <MockNotice />
      <header className="sticky top-0 z-50 mx-auto flex w-full max-w-[1500px] items-center justify-between px-5 py-5 md:px-10">
        <button className="group flex items-center" onClick={() => navigate('/')} aria-label="返回工作台"><BrandMark /></button>
        <nav className="hidden items-center gap-1 rounded-full border border-white/10 bg-white/[0.06] p-1 backdrop-blur-xl md:flex">
          {links.map((link) => <button key={link.href} onClick={() => navigate(link.href)} className={`rounded-full px-4 py-2 text-xs transition ${isActive(link.href) ? 'bg-[#c9f05b] font-semibold text-[#11130f]' : 'text-white/55 hover:bg-white/10 hover:text-white'}`}>{link.label}</button>)}
        </nav>
        <div className="flex items-center gap-3">
          <button className="hidden items-center gap-2 text-xs text-white/60 transition hover:text-[#c9f05b] sm:flex" onClick={() => navigate('/settings')}><span className="h-2 w-2 rounded-full bg-[#c9f05b]" />{userName || '开发者'}<ArrowUpRight size={14} /></button>
          <button className="rounded-full border border-white/10 p-2 text-white md:hidden" onClick={() => setMenuOpen((open) => !open)} aria-label="打开菜单">{menuOpen ? <X size={18} /> : <Menu size={18} />}</button>
          <Button type="text" className="!text-white/60 hover:!text-[#c9f05b]" icon={<LogOut size={16} />} aria-label="退出登录" onClick={() => { clearAuth(); navigate('/login') }} />
        </div>
      </header>
      {menuOpen && <div className="mx-5 mb-3 grid gap-1 rounded-2xl border border-white/10 bg-[#181c17] p-2 md:hidden">{links.map((link) => <button key={link.href} onClick={() => { navigate(link.href); setMenuOpen(false) }} className="rounded-xl px-4 py-3 text-left text-sm text-white/70 hover:bg-white/10">{link.label}</button>)}</div>}
      <main className="w-full max-w-full overflow-x-hidden"><Outlet /></main>
    </div>
  )
}
