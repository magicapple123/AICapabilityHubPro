import { LoaderCircle, X } from 'lucide-react'
import type { ReactNode } from 'react'

import { env } from '@/utils/env'

/**
 * 本地占位登录提示条：Mock 登录签发的是占位 Token（不是合法 JWT），
 * 只要没有额外配置真实 `VITE_DEV_TOKEN`，业务接口都会返回 401。
 */
export function MockNotice() {
  if (!env.useMockLogin || env.devToken) return null
  return (
    <div className="border-b border-amber-300/20 bg-amber-300/10 px-5 py-2 text-center text-xs text-amber-200 md:px-10">
      当前为本地占位登录（VITE_USE_MOCK_LOGIN=true），真实业务接口返回 401。 请把
      web/.env 的该开关设为 false 后用真实账号登录，或配置 VITE_DEV_TOKEN 为网关签发的 JWT。
    </div>
  )
}

/** 页面级加载占位。 */
export function Loading({ label = '正在加载…' }: { label?: string }) {
  return (
    <p className="flex items-center gap-2 text-sm text-white/40">
      <LoaderCircle size={15} className="animate-spin" />
      {label}
    </p>
  )
}

/** 统一错误提示：业务错误码与 message 都来自后端 Result。 */
export function ErrorNote({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="flex flex-wrap items-center gap-4 rounded-2xl border border-red-400/25 bg-red-400/5 px-5 py-4 text-sm text-red-200">
      <span>{message}</span>
      {onRetry && (
        <button onClick={onRetry} className="text-[#c9f05b]">
          重试
        </button>
      )}
    </div>
  )
}

/** 空数据提示。 */
export function EmptyNote({ message }: { message: string }) {
  return <p className="text-sm text-white/35">{message}</p>
}

const STATUS_TONES: Record<string, string> = {
  success: 'bg-[#c9f05b]/15 text-[#c9f05b]',
  degraded: 'bg-amber-400/15 text-amber-300',
  failed: 'bg-red-400/15 text-red-300',
  online: 'bg-[#c9f05b]/15 text-[#c9f05b]',
  draft: 'bg-white/10 text-white/60',
  offline: 'bg-white/10 text-white/45',
  enabled: 'bg-[#c9f05b]/15 text-[#c9f05b]',
  disabled: 'bg-white/10 text-white/45',
}

const STATUS_LABELS: Record<string, string> = {
  success: '成功',
  degraded: '降级',
  failed: '失败',
  online: '已上架',
  draft: '草稿',
  offline: '已下架',
  enabled: '启用',
  disabled: '停用',
}

/** 状态徽标：调用状态与能力/分类状态共用一套配色。 */
export function StatusTag({ value }: { value: string }) {
  const tone = STATUS_TONES[value] ?? 'bg-white/10 text-white/60'
  return (
    <span className={`rounded-full px-3 py-1 text-xs ${tone}`}>
      {STATUS_LABELS[value] ?? value}
    </span>
  )
}

/** 轻量弹窗：深色卡片 + 遮罩，避免引入额外组件库样式。 */
export function Modal({
  title,
  open,
  onClose,
  children,
  footer,
}: {
  title: string
  open: boolean
  onClose: () => void
  children: ReactNode
  footer?: ReactNode
}) {
  if (!open) return null
  return (
    <div className="fixed inset-0 z-[80] flex items-start justify-center overflow-y-auto bg-black/70 px-4 py-10">
      <div className="w-full max-w-xl rounded-[1.5rem] border border-white/10 bg-[#181c17] p-7">
        <div className="mb-6 flex items-center justify-between">
          <h3 className="text-xl font-medium text-white">{title}</h3>
          <button onClick={onClose} className="text-white/40 hover:text-white" aria-label="关闭">
            <X size={18} />
          </button>
        </div>
        {children}
        {footer && <div className="mt-7 flex justify-end gap-3">{footer}</div>}
      </div>
    </div>
  )
}

/** 主按钮 / 次按钮，保持全站一致。 */
export function PrimaryButton({
  children,
  onClick,
  disabled,
  type = 'button',
}: {
  children: ReactNode
  onClick?: () => void
  disabled?: boolean
  type?: 'button' | 'submit'
}) {
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className="rounded-full bg-[#c9f05b] px-5 py-2.5 text-sm font-semibold text-[#11130f] transition hover:bg-white disabled:cursor-not-allowed disabled:opacity-50"
    >
      {children}
    </button>
  )
}

export function GhostButton({
  children,
  onClick,
  disabled,
}: {
  children: ReactNode
  onClick?: () => void
  disabled?: boolean
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="rounded-full border border-white/15 px-4 py-2 text-xs text-white/70 transition hover:border-[#c9f05b] hover:text-[#c9f05b] disabled:cursor-not-allowed disabled:opacity-40"
    >
      {children}
    </button>
  )
}

/** 表单输入行：label + 受控 input。 */
export function Field({
  label,
  value,
  onChange,
  placeholder,
  type = 'text',
}: {
  label: string
  value: string
  onChange: (value: string) => void
  placeholder?: string
  type?: string
}) {
  return (
    <label className="block">
      <span className="mb-2 block text-xs uppercase tracking-[.18em] text-white/40">{label}</span>
      <input
        type={type}
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        className="w-full rounded-xl border border-white/12 bg-[#11130f] px-4 py-3 text-sm text-white outline-none placeholder:text-white/25 focus:border-[#c9f05b]"
      />
    </label>
  )
}

/** 简单分页条：上一页 / 下一页 + 计数。 */
export function Pager({
  page,
  pageSize,
  total,
  onChange,
}: {
  page: number
  pageSize: number
  total: number
  onChange: (page: number) => void
}) {
  const maxPage = Math.max(1, Math.ceil(total / pageSize))
  return (
    <div className="flex items-center justify-between text-xs text-white/45">
      <span>
        共 {total} 条 · 第 {page} / {maxPage} 页
      </span>
      <span className="flex gap-2">
        <GhostButton disabled={page <= 1} onClick={() => onChange(page - 1)}>
          上一页
        </GhostButton>
        <GhostButton disabled={page >= maxPage} onClick={() => onChange(page + 1)}>
          下一页
        </GhostButton>
      </span>
    </div>
  )
}
