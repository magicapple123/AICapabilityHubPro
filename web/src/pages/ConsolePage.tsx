import { Cpu, FolderTree, History, SlidersHorizontal, Users } from 'lucide-react'
import { Navigate, useSearchParams } from 'react-router-dom'
import { PageHeader } from '@/components/PageHeader'
import { CapabilityManager } from '@/components/CapabilityManager'
import { CategoryManager } from '@/components/CategoryManager'
import { AuditLogPanel } from '@/features/console/AuditLogPanel'
import { ModelServicePanel } from '@/features/console/ModelServicePanel'
import { UserUsagePanel } from '@/features/console/UserUsagePanel'

const TABS = [
  { key: 'capabilities', label: '能力管理', icon: SlidersHorizontal },
  { key: 'categories', label: '分类管理', icon: FolderTree },
  { key: 'users-usage', label: '用户与用量', icon: Users },
  { key: 'audit', label: '操作审计', icon: History },
  { key: 'models', label: '模型服务', icon: Cpu },
]

/** P5：`平台用量` 与 `用户管理` 合并为 `用户与用量`，旧链接/书签重定向到新页签。 */
const LEGACY_TABS: Record<string, string> = { statistics: 'users-usage', users: 'users-usage' }

export function ConsolePage() {
  const [params, setParams] = useSearchParams()
  const raw = params.get('tab') ?? ''
  const legacy = LEGACY_TABS[raw]
  if (legacy) return <Navigate to={'/console?tab=' + legacy} replace />
  const tab = TABS.some((item) => item.key === raw) ? raw : 'capabilities'
  return <section className="page"><PageHeader title="运营后台" description="维护能力目录与分类，查看用户用量与操作审计。操作权限以服务端校验为准。" />
    <nav className="settings-tabs" aria-label="运营管理分类">{TABS.map((item) => <button key={item.key} aria-current={tab === item.key ? 'page' : undefined}
      onClick={() => setParams({ tab: item.key })}><item.icon size={16} />{item.label}</button>)}</nav>
    {tab === 'capabilities' && <CapabilityManager />}{tab === 'categories' && <CategoryManager />}{tab === 'users-usage' && <UserUsagePanel />}{tab === 'audit' && <AuditLogPanel />}{tab === 'models' && <ModelServicePanel />}
  </section>
}
