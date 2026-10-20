import { App } from 'antd'
import { Check, UserRound } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { fetchProfile, updateProfile } from '@/api/user'
import { ErrorNote, Loading, StatusTag } from '@/components/ui'
import { useAsyncResource } from '@/hooks/useAsyncResource'

export function ProfileSettings() {
  const resource = useAsyncResource(fetchProfile)
  const [nickname, setNickname] = useState('')
  const [saving, setSaving] = useState(false)
  const inFlight = useRef(false)
  const { message } = App.useApp()
  const profile = resource.data
  useEffect(() => { if (profile) setNickname(profile.nickname || profile.username) }, [profile])
  const changed = !!profile && nickname.trim() !== (profile.nickname || profile.username)
  const save = async () => {
    if (inFlight.current || !nickname.trim() || !changed) return
    inFlight.current = true
    setSaving(true)
    try { await updateProfile({ nickname: nickname.trim() }); void message.success('个人资料已保存'); resource.reload() }
    catch (cause) { void message.error(cause instanceof Error ? cause.message : '保存失败，请稍后重试') }
    finally { inFlight.current = false; setSaving(false) }
  }
  if (resource.loading && !profile) return <div className="panel"><Loading label="正在加载个人资料…" /></div>
  if (resource.error) return <ErrorNote message={resource.error} onRetry={resource.reload} />
  if (!profile) return null
  return <div className="profile-layout"><section className="panel profile-form">
    <div className="panel-head"><div><h2>基本资料</h2><p>更新你在平台上展示的个人信息</p></div><UserRound size={18} className="muted" /></div>
    <div className="profile-banner"><span className="profile-avatar">{(profile.nickname || profile.username).slice(0, 1).toUpperCase()}</span><div><h3>{profile.nickname || profile.username}</h3><p>@{profile.username}</p></div><StatusTag value={profile.status} /></div>
    <form className="panel-body profile-fields" onSubmit={(e) => { e.preventDefault(); void save() }}>
      <label className="field"><span className="field-label">账号</span><input className="form-control" value={profile.username} disabled /><span className="field-hint">账号作为登录标识，暂不支持修改。</span></label>
      <label className="field"><span className="field-label">昵称</span><input className="form-control" name="nickname" required maxLength={32} value={nickname} disabled={saving} onChange={(e) => setNickname(e.target.value)} placeholder="输入你希望展示的昵称" /><span className="field-hint">最多 32 个字符</span></label>
      <div className="profile-metadata"><span>用户编号<b>#{profile.user_id}</b></span><span>注册时间<b>{profile.create_time}</b></span></div>
      <div className="form-actions"><button type="button" className="button-secondary" disabled={!changed || saving} onClick={() => setNickname(profile.nickname || profile.username)}>撤销修改</button><button className="button-primary" type="submit" disabled={!changed || !nickname.trim() || saving}><Check size={14} />{saving ? '保存中…' : '保存修改'}</button></div>
    </form>
  </section><aside className="profile-aside"><h2>关于账号</h2><p>账号为登录标识，暂不支持修改。昵称用于个人资料展示。</p><h3>个人数据</h3><p>会话、调用记录和积分明细按账号保存。</p><h3>访问凭证</h3><p>API Key 在单独页签管理。Secret Key 只在创建时显示一次。</p></aside></div>
}
