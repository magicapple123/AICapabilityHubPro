import { Check, Coins, Copy, KeyRound, Plus, ShieldCheck } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'

import {
  createApiKey,
  disableApiKey,
  fetchApiKeys,
  fetchPoints,
  fetchPointsLogs,
  fetchProfile,
  updateProfile,
  type ApiKeyCreated,
  type ApiKeyItem,
  type PointsAccount,
  type PointsLogItem,
  type Profile,
} from '@/api/user'
import { useAuthStore } from '@/stores/auth'
import {
  EmptyNote,
  ErrorNote,
  Field,
  GhostButton,
  Loading,
  Modal,
  Pager,
  PrimaryButton,
} from '@/components/ui'

const LOG_PAGE_SIZE = 5
const EXPIRE_PATTERN = /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/

export function SettingsPage() {
  const { userName } = useAuthStore()
  const [profile, setProfile] = useState<Profile | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const loadProfile = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setProfile(await fetchProfile())
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '账号资料加载失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadProfile()
  }, [loadProfile])

  const displayName = profile?.nickname || profile?.username || userName || '开发者'

  return (
    <section className="mx-auto max-w-[1500px] px-5 pb-32 pt-12 md:px-10 md:pt-20">
      <p className="mb-5 text-sm text-[#c9f05b]">开发者中心</p>
      <h1 className="text-5xl font-medium tracking-[-.07em] text-[#f4f4ef] md:text-7xl">
        把工作台
        <br />
        <span className="text-white/35">变成你的。</span>
      </h1>

      {loading && (
        <div className="mt-16">
          <Loading label="正在加载账号资料…" />
        </div>
      )}

      {!loading && error && (
        <div className="mt-16">
          <ErrorNote message={error} onRetry={() => void loadProfile()} />
        </div>
      )}

      {!loading && !error && profile && (
        <>
          <div className="mt-16 grid gap-4 lg:grid-cols-[.8fr_1.2fr]">
            <ProfileCard profile={profile} onUpdated={setProfile} fallbackName={displayName} />
            <PointsCard />
          </div>
          <div className="mt-4">
            <ApiKeyCard />
          </div>
        </>
      )}
    </section>
  )
}

function ProfileCard({
  profile,
  onUpdated,
  fallbackName,
}: {
  profile: Profile
  onUpdated: (profile: Profile) => void
  fallbackName: string
}) {
  const [editing, setEditing] = useState(false)
  const [nickname, setNickname] = useState(profile.nickname || profile.username)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')

  const save = async () => {
    const value = nickname.trim()
    if (!value) {
      setMessage('昵称不能为空')
      return
    }
    setSaving(true)
    setMessage('')
    try {
      onUpdated(await updateProfile({ nickname: value }))
      setEditing(false)
      setMessage('昵称已更新')
    } catch (cause) {
      setMessage(cause instanceof Error ? cause.message : '更新失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="rounded-[1.5rem] bg-[#c9f05b] p-7 text-[#11130f]">
      <div className="flex h-16 w-16 items-center justify-center rounded-full bg-[#11130f] text-2xl font-medium text-[#c9f05b]">
        {(profile.nickname || profile.username || fallbackName).slice(0, 1).toUpperCase()}
      </div>
      <p className="mt-16 text-xs font-semibold uppercase tracking-[.18em] text-[#11130f]/55">
        当前账号
      </p>
      <p className="mt-2 text-3xl font-medium tracking-[-.05em]">
        {profile.nickname || profile.username}
      </p>
      <p className="mt-2 text-sm text-[#11130f]/55">
        ID · {profile.user_id} · {profile.username}
      </p>
      <p className="mt-1 text-sm text-[#11130f]/55">
        注册于 {profile.create_time} · 状态 {profile.status === 'normal' ? '正常' : profile.status}
      </p>

      {editing ? (
        <div className="mt-6 space-y-3">
          <input
            value={nickname}
            onChange={(event) => setNickname(event.target.value)}
            className="w-full rounded-xl border border-[#11130f]/20 bg-[#11130f]/5 px-4 py-3 text-sm text-[#11130f] outline-none focus:border-[#11130f]/60"
            placeholder="新的昵称"
          />
          <div className="flex gap-3">
            <button
              onClick={() => void save()}
              disabled={saving}
              className="rounded-full bg-[#11130f] px-5 py-2.5 text-sm font-semibold text-[#c9f05b] disabled:opacity-60"
            >
              {saving ? '保存中…' : '保存昵称'}
            </button>
            <button
              onClick={() => {
                setEditing(false)
                setNickname(profile.nickname || profile.username)
                setMessage('')
              }}
              className="rounded-full border border-[#11130f]/30 px-5 py-2.5 text-sm text-[#11130f]/70"
            >
              取消
            </button>
          </div>
        </div>
      ) : (
        <button
          onClick={() => setEditing(true)}
          className="mt-6 rounded-full border border-[#11130f]/30 px-5 py-2.5 text-sm font-semibold text-[#11130f]/80 transition hover:bg-[#11130f] hover:text-[#c9f05b]"
        >
          修改昵称
        </button>
      )}
      {message && <p className="mt-3 text-xs text-[#11130f]/70">{message}</p>}
    </div>
  )
}

function PointsCard() {
  const [account, setAccount] = useState<PointsAccount | null>(null)
  const [logs, setLogs] = useState<PointsLogItem[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [direction, setDirection] = useState<'' | 'in' | 'out'>('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [pointsData, logPage] = await Promise.all([
        fetchPoints(),
        fetchPointsLogs({
          page,
          page_size: LOG_PAGE_SIZE,
          direction: direction || undefined,
        }),
      ])
      setAccount(pointsData)
      setLogs(logPage.list ?? [])
      setTotal(logPage.total ?? 0)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '积分数据加载失败')
    } finally {
      setLoading(false)
    }
  }, [page, direction])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    setPage(1)
  }, [direction])

  return (
    <div className="rounded-[1.5rem] border border-white/10 bg-[#181c17] p-7">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <Coins className="text-[#c9f05b]" size={22} />
          <div>
            <h2 className="text-xl font-medium text-white">积分账户</h2>
            <p className="mt-1 text-sm text-white/35">注册赠送与调用扣分都会写入流水。</p>
          </div>
        </div>
        <div className="text-right">
          <p className="text-4xl font-medium tracking-[-.05em] text-[#c9f05b]">
            {(account?.balance ?? 0).toLocaleString()}
          </p>
          <p className="text-xs text-white/35">可用积分</p>
        </div>
      </div>

      <div className="mt-8 flex gap-2">
        {[
          { value: '' as const, label: '全部' },
          { value: 'in' as const, label: '收入' },
          { value: 'out' as const, label: '支出' },
        ].map((option) => (
          <button
            key={option.value || 'all'}
            onClick={() => setDirection(option.value)}
            className={`rounded-full px-3 py-1.5 text-xs transition ${
              direction === option.value
                ? 'bg-white text-[#11130f]'
                : 'border border-white/10 text-white/45 hover:border-[#c9f05b] hover:text-[#c9f05b]'
            }`}
          >
            {option.label}
          </button>
        ))}
      </div>

      <div className="mt-5">
        {loading && <Loading label="正在加载积分流水…" />}
        {!loading && error && <ErrorNote message={error} onRetry={() => void load()} />}
        {!loading && !error && logs.length === 0 && <EmptyNote message="暂无积分流水。" />}
        {!loading && !error && logs.length > 0 && (
          <div className="divide-y divide-white/10">
            {logs.map((item) => (
              <div key={item.id} className="flex items-center justify-between gap-4 py-3 text-sm">
                <div className="min-w-0">
                  <p className="truncate text-white/85">
                    {item.remark || (item.biz_type === 'register' ? '注册赠送' : '能力调用扣分')}
                  </p>
                  <p className="mt-1 text-xs text-white/35">
                    {item.create_time} · {item.request_id}
                  </p>
                </div>
                <span className={item.direction === 'in' ? 'text-[#c9f05b]' : 'text-white/60'}>
                  {item.direction === 'in' ? '+' : '-'}
                  {item.amount}
                </span>
                <span className="w-20 text-right text-xs text-white/35">余 {item.balance_after}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="mt-5">
        <Pager page={page} pageSize={LOG_PAGE_SIZE} total={total} onChange={setPage} />
      </div>
    </div>
  )
}

function ApiKeyCard() {
  const [keys, setKeys] = useState<ApiKeyItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState('')
  const [expireTime, setExpireTime] = useState('')
  const [formError, setFormError] = useState('')
  const [created, setCreated] = useState<ApiKeyCreated | null>(null)
  const [copied, setCopied] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const data = await fetchApiKeys()
      setKeys(data.list ?? [])
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'API Key 加载失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const submit = async () => {
    const trimmed = expireTime.trim()
    if (trimmed && !EXPIRE_PATTERN.test(trimmed)) {
      setFormError('过期时间格式应为 YYYY-MM-DD HH:MM:SS，或留空表示永不过期')
      return
    }
    setFormError('')
    try {
      const data = await createApiKey({
        name: name.trim() || undefined,
        expire_time: trimmed || undefined,
      })
      setCreated(data)
      setCreating(false)
      setName('')
      setExpireTime('')
      await load()
    } catch (cause) {
      setFormError(cause instanceof Error ? cause.message : '创建失败')
    }
  }

  const disable = async (apiKeyId: number) => {
    try {
      await disableApiKey(apiKeyId)
      await load()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '禁用失败')
    }
  }

  return (
    <div className="rounded-[1.5rem] border border-white/10 bg-[#181c17] p-7">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <ShieldCheck className="text-[#c9f05b]" size={22} />
          <div>
            <h2 className="text-xl font-medium text-white">访问凭证</h2>
            <p className="mt-1 text-sm text-white/35">
              secret_key 只在创建时返回一次，库内仅保存摘要。
            </p>
          </div>
        </div>
        <PrimaryButton onClick={() => setCreating(true)}>
          <span className="flex items-center gap-2">
            <Plus size={15} /> 新建 API Key
          </span>
        </PrimaryButton>
      </div>

      <div className="mt-7">
        {loading && <Loading label="正在加载访问凭证…" />}
        {!loading && error && <ErrorNote message={error} onRetry={() => void load()} />}
        {!loading && !error && keys.length === 0 && (
          <EmptyNote message="还没有 API Key，创建一个用于本地联调。" />
        )}
        {!loading && !error && keys.length > 0 && (
          <div className="divide-y divide-white/10">
            {keys.map((item) => (
              <div
                key={item.id}
                className="flex flex-wrap items-center justify-between gap-4 py-4 text-sm"
              >
                <div className="min-w-[200px]">
                  <p className="text-white">{item.name || '未命名 Key'}</p>
                  <p className="mt-1 font-mono text-xs text-white/40">
                    {item.access_key} · {item.secret_mask}
                  </p>
                </div>
                <span className="text-xs text-white/40">
                  {item.expire_time ? `过期于 ${item.expire_time}` : '永不过期'}
                </span>
                <span
                  className={`rounded-full px-3 py-1 text-xs ${
                    item.status === 'enabled'
                      ? 'bg-[#c9f05b]/15 text-[#c9f05b]'
                      : 'bg-white/10 text-white/45'
                  }`}
                >
                  {item.status === 'enabled' ? '启用' : '已禁用'}
                </span>
                <GhostButton disabled={item.status !== 'enabled'} onClick={() => void disable(item.id)}>
                  禁用
                </GhostButton>
              </div>
            ))}
          </div>
        )}
      </div>

      <Modal
        title="新建 API Key"
        open={creating}
        onClose={() => setCreating(false)}
        footer={
          <>
            <GhostButton onClick={() => setCreating(false)}>取消</GhostButton>
            <PrimaryButton onClick={() => void submit()}>创建</PrimaryButton>
          </>
        }
      >
        <div className="space-y-4">
          <Field label="备注名" value={name} onChange={setName} placeholder="本地调试" />
          <Field
            label="过期时间（可留空）"
            value={expireTime}
            onChange={setExpireTime}
            placeholder="2027-01-01 00:00:00"
          />
          {formError && <p className="text-sm text-red-300">{formError}</p>}
        </div>
      </Modal>

      <Modal
        title="请立即保存 secret_key"
        open={created !== null}
        onClose={() => setCreated(null)}
        footer={<PrimaryButton onClick={() => setCreated(null)}>我已保存</PrimaryButton>}
      >
        <p className="text-sm text-white/50">
          该密钥不会再展示第二次；关闭后只能看到掩码。
        </p>
        <div className="mt-5 flex items-center gap-3 rounded-xl border border-white/12 bg-[#11130f] px-4 py-3">
          <KeyRound size={16} className="text-[#c9f05b]" />
          <span className="flex-1 break-all font-mono text-xs text-white/80">
            {created?.secret_key}
          </span>
          <button
            onClick={() => {
              void navigator.clipboard?.writeText(created?.secret_key ?? '')
              setCopied(true)
              window.setTimeout(() => setCopied(false), 1600)
            }}
            className="flex items-center gap-1 text-xs text-white/50 hover:text-[#c9f05b]"
          >
            {copied ? <Check size={14} /> : <Copy size={14} />}
            {copied ? '已复制' : '复制'}
          </button>
        </div>
      </Modal>
    </div>
  )
}
