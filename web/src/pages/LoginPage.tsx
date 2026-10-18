import { useState } from 'react'
import { ArrowUpRight, LockKeyhole, UserRound } from 'lucide-react'
import { useLocation, useNavigate } from 'react-router-dom'
import { login, register } from '@/api/auth'
import { useAuthStore } from '@/stores/auth'
import { env } from '@/utils/env'
import { BrandMark } from '@/components/BrandMark'

interface FormState {
  username: string
  password: string
  nickname: string
}

/**
 * 登录 / 注册页：`/login` 与 `/register` 共用同一套视觉与布局，
 * 由当前路径决定模式，避免两份重复代码。
 */
export function LoginPage() {
  const location = useLocation()
  const isRegister = location.pathname === '/register'
  const [form, setForm] = useState<FormState>({ username: '', password: '', nickname: '' })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const navigate = useNavigate()
  const setAuth = useAuthStore((state) => state.setAuth)

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setError('')
    setNotice('')
    const username = form.username.trim()
    if (!username) {
      setError('请输入账号')
      return
    }

    if (isRegister) {
      if (env.useMockLogin) {
        setError(
          '当前是本地占位登录（VITE_USE_MOCK_LOGIN=true），注册接口不可用；请在 web/.env 关闭该开关后重启。',
        )
        return
      }
      if (form.password.length < 8) {
        setError('口令长度需为 8~128 位')
        return
      }
    }

    setLoading(true)
    try {
      if (isRegister) {
        // 注册成功后再用同一凭据登录，省去用户重复输入。
        await register({
          username,
          password: form.password,
          nickname: form.nickname.trim() || undefined,
        })
        const data = await login({ username, password: form.password })
        setAuth(data)
        navigate('/', { replace: true })
        return
      }
      const data = await login({ username, password: form.password })
      setAuth(data)
      navigate(
        (location.state as { from?: { pathname?: string } } | null)?.from?.pathname || '/',
        { replace: true },
      )
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : isRegister ? '注册失败' : '登录失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <main className="grid min-h-screen overflow-hidden bg-[#11130f] text-[#f4f4ef] md:grid-cols-[1.1fr_.9fr]">
      <section className="relative hidden min-h-screen overflow-hidden border-r border-white/10 p-10 md:flex md:flex-col md:justify-between lg:p-16">
        <img
          className="absolute inset-0 h-full w-full object-cover grayscale opacity-35 mix-blend-luminosity"
          src="https://picsum.photos/seed/entry/1400/1800"
          alt=""
        />
        <div className="absolute inset-0 bg-[linear-gradient(135deg,rgba(17,19,15,.2),#11130f_90%)]" />
        <div className="relative">
          <BrandMark />
        </div>
        <div className="relative max-w-2xl">
          <p className="mb-7 text-xs uppercase tracking-[.28em] text-[#c9f05b]">
            Capability-driven execution · Pro
          </p>
          <h1 className="max-w-4xl text-[clamp(3rem,5vw,5.5rem)] font-medium leading-[.95] tracking-[-.07em]">
            让每一次
            <br />
            <span className="text-[#c9f05b]">AI 调用</span>都可核验。
          </h1>
          <p className="mt-7 max-w-md text-base leading-7 text-white/55">
            选择聊天或文本摘要能力，按要求填写参数；在同一条调用链中核对执行结果、积分费用与追踪记录。
          </p>
        </div>
        <p className="relative text-xs uppercase tracking-[.2em] text-white/35">
          AICapabilityHub Pro · Execution / Billing / Tracing
        </p>
      </section>

      <section className="flex min-h-screen flex-col justify-between px-6 py-7 sm:px-10 md:px-16 lg:px-24">
        <div className="md:hidden">
          <BrandMark />
        </div>
        <div className="mx-auto w-full max-w-md self-center py-20">
          <p className="mb-4 text-sm text-[#c9f05b]">{isRegister ? '创建账号' : '欢迎回来'}</p>
          <h2 className="text-4xl font-medium tracking-[-.06em]">
            {isRegister ? '开始你的第一次调用' : '进入你的工作台'}
          </h2>
          <p className="mt-4 text-sm leading-6 text-white/45">
            {isRegister
              ? '注册即创建积分账户并赠送初始积分，随后自动登录。'
              : '用开发者账号登录，继续调试你的下一次调用。'}
          </p>

          <form className="mt-10 space-y-5" onSubmit={submit}>
            <label className="block">
              <span className="mb-2 block text-xs uppercase tracking-[.18em] text-white/45">账号</span>
              <span className="flex items-center gap-3 border-b border-white/15 py-3 focus-within:border-[#c9f05b]">
                <UserRound size={17} className="text-white/35" />
                <input
                  required
                  value={form.username}
                  onChange={(event) => setForm({ ...form, username: event.target.value })}
                  className="w-full bg-transparent text-base outline-none placeholder:text-white/25"
                  placeholder="3~32 位字母 / 数字 / 下划线 / 连字符"
                  autoComplete="username"
                />
              </span>
            </label>

            <label className="block">
              <span className="mb-2 block text-xs uppercase tracking-[.18em] text-white/45">密码</span>
              <span className="flex items-center gap-3 border-b border-white/15 py-3 focus-within:border-[#c9f05b]">
                <LockKeyhole size={17} className="text-white/35" />
                <input
                  type="password"
                  value={form.password}
                  onChange={(event) => setForm({ ...form, password: event.target.value })}
                  className="w-full bg-transparent text-base outline-none placeholder:text-white/25"
                  placeholder={isRegister ? '至少 8 位' : '请输入账号密码'}
                  autoComplete={isRegister ? 'new-password' : 'current-password'}
                />
              </span>
            </label>

            {isRegister && (
              <label className="block">
                <span className="mb-2 block text-xs uppercase tracking-[.18em] text-white/45">
                  昵称（可选）
                </span>
                <span className="flex items-center gap-3 border-b border-white/15 py-3 focus-within:border-[#c9f05b]">
                  <UserRound size={17} className="text-white/35" />
                  <input
                    value={form.nickname}
                    onChange={(event) => setForm({ ...form, nickname: event.target.value })}
                    className="w-full bg-transparent text-base outline-none placeholder:text-white/25"
                    placeholder="默认等于账号名"
                  />
                </span>
              </label>
            )}

            {error && (
              <p className="border border-red-400/30 bg-red-400/10 p-3 text-sm text-red-200">{error}</p>
            )}
            {notice && <p className="text-sm text-[#c9f05b]">{notice}</p>}

            <button
              disabled={loading}
              className="group mt-5 flex w-full items-center justify-between rounded-full bg-[#c9f05b] px-6 py-4 text-sm font-semibold text-[#11130f] transition hover:bg-white disabled:cursor-wait disabled:opacity-60"
            >
              {loading ? (isRegister ? '正在注册…' : '正在连接…') : isRegister ? '注册并登录' : '进入工作台'}
              <ArrowUpRight size={18} className="transition group-hover:translate-x-1 group-hover:-translate-y-1" />
            </button>
          </form>

          <div className="mt-7 flex flex-wrap items-center justify-between gap-3 text-xs text-white/40">
            {isRegister ? (
              <button onClick={() => navigate('/login')} className="hover:text-[#c9f05b]">
                已有账号？去登录
              </button>
            ) : (
              <button onClick={() => navigate('/register')} className="hover:text-[#c9f05b]">
                还没有账号？注册一个
              </button>
            )}
            <span>
              {env.useMockLogin ? '本地占位登录已开启' : '走网关 /api/user/login'}
            </span>
          </div>
          <p className="mt-4 text-xs leading-5 text-white/30">
             默认使用真实网关登录；如需脱离后端做页面演示，可在 web/.env 显式设置 `VITE_USE_MOCK_LOGIN=true`。
          </p>
        </div>
        <p className="text-center text-xs text-white/25">安全连接 · 统一身份透传 · 可观测调用</p>
      </section>
    </main>
  )
}
