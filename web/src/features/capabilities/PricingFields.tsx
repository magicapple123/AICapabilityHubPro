import type { BillingMode } from '@/api/capability'
import { FieldError, FormSection } from './editorUi'
import type { CapabilityFormState, FieldErrors } from './capabilityFormModel'

const MODES: ReadonlyArray<{ value: BillingMode; label: string; hint: string }> = [
  { value: 'per_call', label: '按次', hint: '每次成功调用扣固定积分' },
  { value: 'per_token', label: '按 token', hint: '按输入/输出 token 分别计价' },
  { value: 'per_unit', label: '按件', hint: '按产出件数计价，如图片张数' },
]

/** P8：计价三选一；只展示当前模式的价格输入，其余字段提交时按 0 归一。 */
export function PricingFields({ form, errors, update }: {
  form: CapabilityFormState
  errors: FieldErrors
  update: (patch: Partial<CapabilityFormState>) => void
}) {
  return <FormSection title="计价" description="计价模式与对应的价格字段由服务端做最终校验，这里只做提前反馈。">
    <div className="cap-billing-modes" role="group" aria-label="计价模式">
      {MODES.map((mode) => <button key={mode.value} type="button" aria-pressed={form.billing_mode === mode.value}
        title={mode.hint} onClick={() => update({ billing_mode: mode.value })}>{mode.label}</button>)}
    </div>
    {form.billing_mode === 'per_call' && <div className="editor-row">
      <div className="field">
        <label className="field-label" htmlFor="cap-price-call">每次调用积分</label>
        <input id="cap-price-call" className="form-control" type="number" min={0} step={1}
          value={form.price_per_call} onChange={(e) => update({ price_per_call: e.target.value })} />
        <p className="field-hint">0 表示免费能力。</p>
      </div>
    </div>}
    {form.billing_mode === 'per_token' && <div className="editor-row">
      <div className="field">
        <label className="field-label" htmlFor="cap-price-input">输入单价 / 1K token</label>
        <input id="cap-price-input" className="form-control" type="number" min={0} step={1}
          value={form.price_per_1k_input} onChange={(e) => update({ price_per_1k_input: e.target.value })} />
      </div>
      <div className="field">
        <label className="field-label" htmlFor="cap-price-output">输出单价 / 1K token</label>
        <input id="cap-price-output" className="form-control" type="number" min={0} step={1}
          value={form.price_per_1k_output} onChange={(e) => update({ price_per_1k_output: e.target.value })} />
      </div>
    </div>}
    {form.billing_mode === 'per_unit' && <div className="editor-row">
      <div className="field">
        <label className="field-label" htmlFor="cap-price-unit">单价 / 每件</label>
        <input id="cap-price-unit" className="form-control" type="number" min={1} step={1}
          value={form.price_per_unit} onChange={(e) => update({ price_per_unit: e.target.value })} />
      </div>
      <div className="field">
        <label className="field-label" htmlFor="cap-unit">计价单位</label>
        <input id="cap-unit" className="form-control" maxLength={16} placeholder="张"
          value={form.unit} onChange={(e) => update({ unit: e.target.value })} />
        <FieldError message={errors.unit} />
      </div>
    </div>}
    <FieldError message={errors.price} />
    <p className="field-hint">失败、降级与预算拦截的调用不计费，实际金额以服务端结算为准。</p>
  </FormSection>
}
