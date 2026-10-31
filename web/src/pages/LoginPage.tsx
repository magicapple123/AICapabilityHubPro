import { Eye, EyeOff, LoaderCircle } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { login, register } from '@/api/auth'
import { BrandMark } from '@/components/BrandMark'
import { ErrorNote } from '@/components/ui'
import { useAuthStore } from '@/stores/auth'
import { env } from '@/utils/env'

export function LoginPage() {
  const location = useLocation()
  const [search] = useSearchParams()
  const isRegister = location.pathname === '/register'
  const [form, setForm] = useState({ username: '', password: '', nickname: '' })
  const [visible, setVisible] = useState(false)
  const [caps, setCaps] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const locked = useRef(false)
  const navigate = useNavigate()
  const setAuth = useAuthStore((state) => state.setAuth)
  const update = (key: keyof typeof form, value: string) => {
    setForm((old) => ({ ...old, [key]: value }))
    setError('')
  }
  useEffect(() => { document.title = (isRegister ? '注册' : '登录') + ' · AICapabilityHub Pro' }, [isRegister])
  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (locked.current) return
    setError('')
    if (isRegister && env.useMockLogin) { setError('演示登录模式暂不支持注册，请使用已有账号。'); return }
    locked.current = true
    setLoading(true)
    try {
      const payload = { username: form.username.trim(), password: form.password }
      if (isRegister) await register({ ...payload, nickname: form.nickname.trim() || undefined })
      const data = await login(payload)
      setAuth(data)
      const from = (location.state as { from?: { pathname?: string; search?: string; hash?: string } } | null)?.from
      const target = from?.pathname ? from.pathname + (from.search || '') + (from.hash || '') : search.get('redirect') || '/'
      navigate(target.startsWith('/') && !target.startsWith('//') ? target : '/', { replace: true })
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : isRegister ? '注册失败，请稍后重试' : '登录失败，请检查账号与密码')
    } finally { locked.current = false; setLoading(false) }
  }
  return <main className="auth-page">
    <div className="auth-card">
      <section className="auth-brand" aria-label="平台简介">
        <div className="auth-brand-top"><Link to="/login" aria-label="AICapabilityHub Pro 首页"><BrandMark /></Link></div>
        <div className="auth-brand-main">
          <p className="auth-eyebrow">Access console</p>
          <h1 className="auth-title">把每一次能力调用，<br />变成可核对的账。</h1>
          <p className="auth-desc">统一的鉴权、限流与计费。每次执行都会返回收据，记录耗时、消耗积分与 requestId，用于对账和排障。</p>
          <div className="auth-receipt">
            <span>最近一次执行</span>
            <div className="auth-receipt-row"><code>req_8f3a2c91d4</code><span>hub-fast-1</span><span>1.82s</span><b>−5 积分</b></div>
          </div>
          <div className="auth-stats">
            <div className="auth-stat"><b>6</b><span>已上架能力</span></div>
            <div className="auth-stat"><b>1.6s</b><span>P95 延迟</span></div>
            <div className="auth-stat"><b>98.6%</b><span>调用成功率</span></div>
          </div>
          <div className="auth-ruler" aria-hidden="true" />
        </div>
        <div className="auth-legal"><span>© 2026 AICapabilityHub Pro</span><span>服务状态正常</span></div>
      </section>

      <section className="auth-panel">
        <div className="auth-entry">
          <header className="auth-entry-heading"><p>开发者控制台</p><h1>{isRegister ? '创建账号' : '登录工作空间'}</h1>
            <span>{isRegister ? '注册后即可管理能力、调试和用量。' : '使用你的账号继续访问。'}</span></header>
          <form onSubmit={(event) => void submit(event)} className="auth-form">
            <label className="field"><span className="field-label">账号</span><input className="form-control" required name="username" autoComplete="username" maxLength={32}
              minLength={isRegister ? 3 : undefined} pattern={isRegister ? '[A-Za-z0-9_-]{3,32}' : undefined}
              placeholder="请输入账号" value={form.username} onChange={(e) => update('username', e.target.value)} disabled={loading} />
              {isRegister && <span className="field-hint">3–32 位字母、数字、下划线或连字符</span>}</label>
            <label className="field"><span className="field-label">密码</span><span className="password-control"><input className="form-control" required name="password" type={visible ? 'text' : 'password'}
              autoComplete={isRegister ? 'new-password' : 'current-password'} minLength={isRegister ? 8 : undefined} maxLength={128}
              placeholder={isRegister ? '至少 8 位字符' : '请输入密码'} value={form.password} disabled={loading}
              onKeyUp={(e) => setCaps(e.getModifierState('CapsLock'))} onBlur={() => setCaps(false)} onChange={(e) => update('password', e.target.value)} />
              <button type="button" aria-label={visible ? '隐藏密码' : '显示密码'} aria-pressed={visible} onClick={() => setVisible((value) => !value)}>{visible ? <EyeOff size={16} /> : <Eye size={16} />}</button></span>
              {caps && <span className="field-hint auth-caps">大写锁定已开启</span>}</label>
            {isRegister && <label className="field"><span className="field-label">昵称 <span className="muted">（可选）</span></span><input className="form-control" maxLength={32} autoComplete="nickname"
              placeholder="用于个人资料展示" value={form.nickname} onChange={(e) => update('nickname', e.target.value)} disabled={loading} /></label>}
            {error && <ErrorNote message={error} />}
            <button type="submit" className="button-primary auth-submit" disabled={loading}>{loading && <LoaderCircle size={16} className="spinner" />}{loading ? '请稍候…' : isRegister ? '创建账号并登录' : '登录工作空间'}</button>
          </form>
          <p className="auth-switch">{isRegister ? '已有账号？' : '还没有账号？'}<Link to={isRegister ? '/login' : '/register'} state={location.state} onClick={() => setError('')}>{isRegister ? '返回登录' : '创建账号'}</Link></p>
          {!isRegister && import.meta.env.DEV && <div className="auth-demo"><span>本地演示</span><button type="button" disabled={loading}
            onClick={() => { setForm({ username: 'demo', password: 'demo123456', nickname: '' }); setError('') }}>填入演示账号</button></div>}
          {env.useMockLogin && <p className="auth-mock">当前为占位登录模式，业务功能需要后端支持。</p>}
        </div>
      </section>
    </div>
  </main>
}
