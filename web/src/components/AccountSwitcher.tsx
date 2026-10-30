import { LogIn, Trash2 } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { isExpired } from '@/stores/accountVault'
import { useAuthStore } from '@/stores/auth'
import { Modal } from './ui'

/**
 * 多账号快速切换：列出本机登录过的账号，点一下换回对应令牌。
 * 这里只交换本地令牌，不代替服务端鉴权；令牌过期会被置灰。
 */
export function AccountSwitcher({ open, onClose }: { open: boolean; onClose: () => void }) {
  const navigate = useNavigate()
  const { accounts, username, switchTo, dropSession, removeSavedAccount } = useAuthStore()
  const toLogin = () => {
    onClose()
    dropSession()
    navigate('/login', { replace: true })
  }
  const use = (name: string) => {
    if (!switchTo(name)) return
    onClose()
    // 整页重载，确保各页面的数据都按新身份重新拉取。
    window.location.assign('/')
  }
  const footer = <div className="account-switcher-footer">
    <button className="button-secondary" onClick={toLogin}><LogIn size={14} />使用其他账号登录</button>
  </div>
  return <Modal title="切换账号" open={open} onClose={onClose} footer={footer}>
    {!accounts.length
      ? <p className="inline-note">本机还没有保存其他账号。用另一个账号登录一次，之后就能在这里一键切换。</p>
      : <ul className="account-list">{accounts.map((account) => {
        const expired = isExpired(account)
        const current = account.username === username
        return <li key={account.username} className={'account-row' + (current ? ' current' : '')}>
          <span className="account-avatar">{(account.displayName || account.username).slice(0, 1).toUpperCase()}</span>
          <span className="account-info">
            <strong>{account.displayName || account.username}{current && <em>当前</em>}</strong>
            <small>
              @{account.username} · {account.role === 'admin' ? '管理员' : '普通用户'}
              {expired && ' · 登录已过期'}
            </small>
          </span>
          {!current && <button className="button-secondary account-action" disabled={expired}
            onClick={() => use(account.username)}>{expired ? '已过期' : '切换'}</button>}
          {!current && <button className="icon-button" aria-label={'删除账号 ' + account.username}
            onClick={() => removeSavedAccount(account.username)}><Trash2 size={14} /></button>}
        </li>
      })}</ul>}
    <p className="inline-note">切换只改用本机保存的登录令牌，不会重新校验密码；令牌过期或账号被禁用时，服务端仍会拒绝。</p>
  </Modal>
}
