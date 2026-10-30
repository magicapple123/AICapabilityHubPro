import { App, Drawer, Dropdown } from 'antd'
import { ArrowLeftRight, ArrowUpRight, BookOpen, ChevronDown, ChevronRight, CircleHelp, LogOut, Menu, PanelLeftClose, Search, Settings2 } from 'lucide-react'
import { Suspense, useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { fetchPoints } from '@/api/user'
import { useAsyncResource } from '@/hooks/useAsyncResource'
import { useAuthStore } from '@/stores/auth'
import { formatNumber } from '@/lib/dateRange'
import { AccountSwitcher } from './AccountSwitcher'
import { BrandMark } from './BrandMark'
import { CommandMenu } from './CommandMenu'
import { accountLinks, navigationLinks, workspaceLinks } from './navigation'
import { Loading, MockNotice, Modal } from './ui'

export function AppShell() {
  const location = useLocation()
  const navigate = useNavigate()
  const { modal } = App.useApp()
  const { userName, clearAuth } = useAuthStore()
  const points = useAsyncResource(fetchPoints)
  const refreshPoints = points.reload
  const [mobileOpen, setMobileOpen] = useState(false)
  const [commandOpen, setCommandOpen] = useState(false)
  const [helpOpen, setHelpOpen] = useState(false)
  const [switcherOpen, setSwitcherOpen] = useState(false)
  const [collapsed, setCollapsed] = useState(false)
  const active = navigationLinks.find((link) => link.href === location.pathname)
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); setCommandOpen((v) => !v) }
    }
    const balance = () => refreshPoints()
    window.addEventListener('keydown', handler)
    window.addEventListener('hub:balance-changed', balance)
    return () => { window.removeEventListener('keydown', handler); window.removeEventListener('hub:balance-changed', balance) }
  }, [refreshPoints])
  useEffect(() => {
    window.scrollTo({ top: 0 })
    document.title = (active?.label ?? '工作空间') + ' · AICapabilityHub Pro'
  }, [location.pathname, active?.label])
  const logout = () => modal.confirm({
    title: '退出当前账号？', content: '退出后需要重新登录才能访问工作空间。', okText: '退出登录', cancelText: '继续使用',
    onOk: () => { clearAuth(); navigate('/login', { replace: true }) },
  })
  const sidebar = <div className="sidebar-inner">
    <NavLink to="/" className="sidebar-brand" onClick={() => setMobileOpen(false)}><BrandMark /></NavLink>
    <div className="workspace-badge"><span>个人空间</span><small>{userName || '开发者'}</small></div>
    <p className="nav-group-label">工作空间</p>
    <nav aria-label="工作空间导航">{workspaceLinks.map((link) => <NavLink key={link.href} to={link.href} end={link.href === '/'}
      onClick={() => setMobileOpen(false)} className={({ isActive }) => 'sidebar-link' + (isActive ? ' active' : '')} title={collapsed ? link.label : undefined}>
      <link.icon size={18} strokeWidth={1.6} /><span>{link.label}</span></NavLink>)}</nav>
    <p className="nav-group-label nav-second">管理与设置</p>
    <nav aria-label="管理与设置导航">{accountLinks.map((link) => <NavLink key={link.href} to={link.href}
      onClick={() => setMobileOpen(false)} className={({ isActive }) => 'sidebar-link' + (isActive ? ' active' : '')} title={collapsed ? link.label : undefined}>
      <link.icon size={18} strokeWidth={1.6} /><span>{link.label}</span></NavLink>)}</nav>
    <div className="sidebar-bottom">
      <div className="sidebar-balance"><div><span>可用积分</span><strong>{points.error ? '暂不可用' : points.loading && !points.data ? '···' : formatNumber(points.data?.balance)}</strong></div>
        <button onClick={() => { navigate('/settings?tab=points'); setMobileOpen(false) }}>积分明细<ChevronRight size={13} /></button>
      </div>
      <button className="sidebar-help" onClick={() => { setHelpOpen(true); setMobileOpen(false) }}><CircleHelp size={17} /><span>使用指南</span><ArrowUpRight size={13} /></button>
      <div className="sidebar-footer"><span className="sidebar-version">AICapabilityHub Pro</span><button aria-label={collapsed ? '展开侧栏' : '收起侧栏'}
        className="collapse-button" onClick={() => setCollapsed((value) => !value)}><PanelLeftClose size={16} /></button></div>
    </div>
  </div>
  return <div className={'application' + (collapsed ? ' sidebar-collapsed' : '')}>
    <a href="#main-content" className="skip-link">跳转到主要内容</a>
    <aside className="desktop-sidebar">{sidebar}</aside>
    <Drawer title={<BrandMark />} placement="left" width={280} open={mobileOpen} onClose={() => setMobileOpen(false)}
      styles={{ body: { padding: 0, background: '#ffffff' } }}><div className="mobile-sidebar">{sidebar}</div></Drawer>
    <div className="application-main">
      <header className="topbar"><div className="topbar-inner">
        <div className="breadcrumb"><button className="icon-button mobile-menu" aria-label="打开导航菜单" onClick={() => setMobileOpen(true)}><Menu size={19} /></button>
          <span className="breadcrumb-parent">工作空间</span><ChevronRight size={13} /><strong>{active?.label ?? '页面'}</strong></div>
        <div className="topbar-actions"><button className="global-search" onClick={() => setCommandOpen(true)}><Search size={15} /><span>搜索页面或功能</span><kbd>Ctrl K</kbd></button>
          <span className="topbar-divider" /><button className="icon-button help-button" aria-label="使用指南" onClick={() => setHelpOpen(true)}><BookOpen size={18} /></button>
          <Dropdown menu={{ items: [
            { key: 'settings', icon: <Settings2 size={15} />, label: '账号设置', onClick: () => navigate('/settings') },
            { key: 'switch', icon: <ArrowLeftRight size={15} />, label: '切换账号', onClick: () => setSwitcherOpen(true) },
            { type: 'divider' }, { key: 'logout', icon: <LogOut size={15} />, label: '退出登录', danger: true, onClick: logout },
          ] }} trigger={['click']}>
            <button className="account-trigger" aria-label="账号菜单"><span className="avatar">{(userName || 'D').slice(0, 1).toUpperCase()}</span><span>{userName || '开发者'}</span><ChevronDown size={12} /></button>
          </Dropdown>
        </div>
      </div></header>
      <MockNotice />
      <main id="main-content" tabIndex={-1}><Suspense fallback={<Loading label="正在打开页面…" />}><Outlet /></Suspense></main>
      <footer className="app-footer"><span>© {new Date().getFullYear()} AICapabilityHub Pro</span><span>开发者控制台</span></footer>
    </div>
    <CommandMenu open={commandOpen} onClose={() => setCommandOpen(false)} />
    <AccountSwitcher open={switcherOpen} onClose={() => setSwitcherOpen(false)} />
    <Modal title="从选择能力到核对结果" open={helpOpen} onClose={() => setHelpOpen(false)}>
      <ol className="help-steps"><li><b>发现能力</b><p>在能力市场选择聊天或文本摘要，查看每次调用的积分价格。</p></li>
        <li><b>在线调试</b><p>根据输入要求填写参数。聊天支持多轮上下文；摘要使用独立文本输入。</p></li>
        <li><b>核对调用</b><p>查看结果收据中的实际费用和 requestId，在调用记录中核对明细。降级执行不收费。</p></li></ol>
      <button className="button-primary" onClick={() => { setHelpOpen(false); navigate('/capabilities') }}>探索能力市场<ArrowUpRight size={14} /></button>
    </Modal>
  </div>
}
