import { App, Input, InputNumber } from 'antd'
import { useState } from 'react'
import { adjustAdminUserPoints, type AdminUser } from '@/api/admin'
import { ErrorNote, GhostButton, Modal } from '@/components/ui'
import { formatNumber } from '@/lib/dateRange'

/** 与后端 `admin_service.MAX_ADJUST_AMOUNT` 保持一致（此前的需求文档写 10000，以代码为准）。 */
const MAX_ADJUST = 1_000_000
const QUICK_AMOUNTS = [10, 50, 100, -10, -50, -100]

/**
 * 调分弹窗（P7）：替代原来的两次 `window.prompt`。
 * 前端只做提前反馈，最终仍以后端 `POST /api/user/admin/users/{id}/points` 为准。
 */
export function PointsAdjustModal({ user, onClose, onAdjusted }: {
  user: AdminUser
  onClose: () => void
  onAdjusted: (balance: number) => void
}) {
  const { message } = App.useApp()
  const [amount, setAmount] = useState<number | null>(null)
  const [reason, setReason] = useState('')
  const [reasonError, setReasonError] = useState('')
  const [serverError, setServerError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const balance = user.balance
  const value = amount ?? 0
  const after = balance + value
  const overBalance = value < 0 && -value > balance
  const amountError = amount === null ? '' : value === 0 ? '不能为 0'
    : Math.abs(value) > MAX_ADJUST ? `单次上限 ${formatNumber(MAX_ADJUST)}`
      : overBalance ? `最多可扣 ${formatNumber(balance)}` : ''
  const canSubmit = amount !== null && !amountError && !submitting

  const submit = async () => {
    if (!canSubmit) return
    if (!reason.trim()) {
      setReasonError('请填写调整原因（会写入审计）')
      return
    }
    setSubmitting(true)
    setServerError('')
    setReasonError('')
    try {
      const result = await adjustAdminUserPoints(user.id, value, reason.trim())
      void message.success(
        `已调整 ${value > 0 ? '+' : ''}${formatNumber(value)}，当前余额 ${formatNumber(result.balance)}`,
      )
      onAdjusted(result.balance)
    } catch (cause) {
      // 3001「余额不足，无法扣减」等业务错误渲染在表单顶部，不再用 window.alert。
      setServerError(cause instanceof Error ? cause.message : '调整失败，请稍后重试')
    } finally {
      setSubmitting(false)
    }
  }

  const footer = (
    <div className="points-modal-foot">
      <GhostButton onClick={onClose} disabled={submitting}>取消</GhostButton>
      <button
        type="submit" form="points-adjust-form" disabled={!canSubmit}
        className={value < 0 ? 'button-primary is-danger' : 'button-primary'}
      >
        {submitting ? '提交中…' : value < 0 ? `确认扣减 ${formatNumber(-value)}` : '确认调整'}
      </button>
    </div>
  )

  return (
    <Modal title={`调整积分 · ${user.username} #${user.id}`} open onClose={onClose} footer={footer}>
      <form
        id="points-adjust-form" className="points-form"
        onSubmit={(event) => { event.preventDefault(); void submit() }}
      >
        {serverError ? <ErrorNote message={serverError} /> : null}

        <div className="points-form-row"><span>当前余额</span><strong>{formatNumber(balance)} 积分</strong></div>

        <div className="points-field">
          <span className="points-label">调整数量</span>
          <InputNumber
            value={amount} onChange={setAmount} precision={0} step={10} disabled={submitting}
            min={-MAX_ADJUST} max={MAX_ADJUST} style={{ width: '100%' }} placeholder="正数增加，负数扣减"
            addonAfter="积分"
          />
          <span className="points-quick">
            {QUICK_AMOUNTS.map((delta) => (
              <button
                key={delta} type="button" className="button-secondary" disabled={submitting}
                onClick={() => setAmount((current) => (current ?? 0) + delta)}
              >
                {delta > 0 ? '+' : '−'}{Math.abs(delta)}
              </button>
            ))}
          </span>
          {amountError ? <span className="points-error">{amountError}</span> : null}
        </div>

        <div className="points-form-row">
          <span>调整后</span>
          <strong className={'points-after' + (after < 0 ? ' is-negative' : '')}>{formatNumber(after)} 积分</strong>
        </div>

        <div className="points-field">
          <span className="points-label">调整原因</span>
          <Input.TextArea
            value={reason} onChange={(event) => { setReason(event.target.value); setReasonError('') }}
            maxLength={200} rows={3} showCount disabled={submitting}
            placeholder="例：活动奖励 / 误扣补回 / 违规扣减"
          />
          {reasonError ? <span className="points-error">{reasonError}</span> : null}
          {!reasonError && reason.trim() && reason.trim().length < 4
            ? <span className="points-hint">建议写清事由，便于日后审计追溯</span> : null}
        </div>

        <p className="points-note">将写入积分流水（admin_adjust）与操作审计，提交后不可撤销。</p>
      </form>
    </Modal>
  )
}
