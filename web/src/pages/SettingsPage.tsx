import { Coins, KeyRound, UserRound } from 'lucide-react'
import { useSearchParams } from 'react-router-dom'
import { PageHeader } from '@/components/PageHeader'
import { ProfileSettings } from '@/features/settings/ProfileSettings'
import { PointsSettings } from '@/features/settings/PointsSettings'
import { ApiKeySettings } from '@/features/settings/ApiKeySettings'

const TABS = [{ id: 'profile', label: '个人资料', icon: UserRound }, { id: 'points', label: '积分账户', icon: Coins }, { id: 'keys', label: 'API Key', icon: KeyRound }]
export function SettingsPage() {
  const [params, setParams] = useSearchParams()
  const tab = TABS.some((item) => item.id === params.get('tab')) ? params.get('tab') : 'profile'
  return <section className="page">
    <PageHeader title="账号设置" description="管理个人资料、积分账户和访问凭证。" />
    <nav className="settings-tabs" aria-label="账号设置分类">{TABS.map((item) => <button key={item.id}
      aria-current={tab === item.id ? 'page' : undefined} onClick={() => setParams({ tab: item.id })}><item.icon size={16} />{item.label}</button>)}</nav>
    {tab === 'profile' && <ProfileSettings />}{tab === 'points' && <PointsSettings />}{tab === 'keys' && <ApiKeySettings />}
  </section>
}
