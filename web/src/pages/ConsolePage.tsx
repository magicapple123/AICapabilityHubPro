import { BarChart3, FolderTree, SlidersHorizontal } from 'lucide-react'
import { useSearchParams } from 'react-router-dom'
import { PageHeader } from '@/components/PageHeader'
import { CapabilityManager } from '@/components/CapabilityManager'
import { CategoryManager } from '@/components/CategoryManager'
import { PlatformUsage } from '@/features/console/PlatformUsage'

const TABS = [{ key: 'capabilities', label: '能力管理', icon: SlidersHorizontal }, { key: 'categories', label: '分类管理', icon: FolderTree }, { key: 'statistics', label: '平台用量', icon: BarChart3 }]
export function ConsolePage() {
  const [params, setParams] = useSearchParams()
  const tab = TABS.some((item) => item.key === params.get('tab')) ? params.get('tab') : 'capabilities'
  return <section className="page"><PageHeader title="运营后台" description="维护能力目录与分类，查看平台用量。操作权限以服务端校验为准。" />
    <nav className="settings-tabs" aria-label="运营管理分类">{TABS.map((item) => <button key={item.key} aria-current={tab === item.key ? 'page' : undefined}
      onClick={() => setParams({ tab: item.key })}><item.icon size={16} />{item.label}</button>)}</nav>
    {tab === 'capabilities' && <CapabilityManager />}{tab === 'categories' && <CategoryManager />}{tab === 'statistics' && <PlatformUsage />}
  </section>
}
