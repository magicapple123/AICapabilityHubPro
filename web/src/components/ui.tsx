import { Modal as AntModal } from 'antd'
import { AlertCircle, ChevronLeft, ChevronRight, LoaderCircle, RotateCw } from 'lucide-react'
import type { ReactNode } from 'react'
import { env } from '@/utils/env'

export function MockNotice() {
  if (!env.useMockLogin || env.devToken) return null
  return <div className="error-note">当前使用本地演示登录，部分功能需要真实账号。请联系项目维护者切换登录配置。</div>
}
export function Loading({ label = '正在加载…' }: { label?: string }) {
  return <div className="loading-state" role="status"><LoaderCircle size={17} className="spinner" />{label}</div>
}
export function ErrorNote({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return <div className="error-note" role="alert"><AlertCircle size={16} /><span className="flex-1">{message}</span>
    {onRetry && <button type="button" className="text-link" onClick={onRetry}><RotateCw size={13} />重试</button>}</div>
}
export function EmptyNote({ message, action }: { message: string; action?: ReactNode }) {
  return <div className="empty-state"><p>{message}</p>{action}</div>
}
const LABELS: Record<string, string> = {
  success: '成功', degraded: '已降级', failed: '失败', online: '已上架',
  draft: '草稿', offline: '已下架', enabled: '已启用', disabled: '已禁用', normal: '正常',
}
export function StatusTag({ value }: { value: string }) {
  const tone = ['success', 'online', 'enabled', 'normal'].includes(value) ? 'good'
    : value === 'degraded' ? 'warn' : value === 'failed' ? 'bad' : 'neutral'
  return <span className={'status-tag status-' + tone}><span className="status-dot" />{LABELS[value] ?? value}</span>
}
export function Modal({ title, open, onClose, children, footer }: {
  title: string; open: boolean; onClose: () => void; children: ReactNode; footer?: ReactNode
}) {
  return <AntModal title={title} open={open} onCancel={onClose} footer={footer ?? null}
    centered width={560}
    styles={{ body: { paddingTop: 18, maxHeight: 'calc(100vh - 210px)', overflowY: 'auto' }, footer: { paddingTop: 15 } }}>
    {children}
  </AntModal>
}
export function PrimaryButton({ children, onClick, disabled, type = 'button' }: {
  children: ReactNode; onClick?: () => void; disabled?: boolean; type?: 'button' | 'submit'
}) {
  return <button type={type} className="button-primary" onClick={onClick} disabled={disabled}>{children}</button>
}
export function GhostButton({ children, onClick, disabled }: {
  children: ReactNode; onClick?: () => void; disabled?: boolean
}) {
  return <button type="button" className="button-secondary" onClick={onClick} disabled={disabled}>{children}</button>
}
export function Field({ label, value, onChange, placeholder, type = 'text' }: {
  label: string; value: string; onChange: (value: string) => void; placeholder?: string; type?: string
}) {
  return <label className="field"><span className="field-label">{label}</span>
    <input className="form-control" type={type} value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} /></label>
}
export function Pager({ page, pageSize, total, onChange }: {
  page: number; pageSize: number; total: number; onChange: (page: number) => void
}) {
  const max = Math.max(1, Math.ceil(total / pageSize))
  return <div className="pager"><span>共 {total} 条 · 第 {page} / {max} 页</span><span className="pager-buttons">
    <button className="button-secondary" aria-label="上一页" disabled={page <= 1} onClick={() => onChange(page - 1)}><ChevronLeft size={13} />上一页</button>
    <button className="button-secondary" aria-label="下一页" disabled={page >= max} onClick={() => onChange(page + 1)}>下一页<ChevronRight size={13} /></button>
  </span></div>
}
