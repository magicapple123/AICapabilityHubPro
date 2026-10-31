import { ChevronDown, LoaderCircle, Send, SlidersHorizontal } from 'lucide-react'
import { Fragment, useRef } from 'react'
import { schemaFields } from './schemaInput'
import { SUMMARY_NOTICE, looksLikeQuestion } from './summaryNotice'
import type { FormValues } from './types'

export function SchemaForm({ schema, values, onChange, onSend, disabled, sending, code }: {
  schema: Record<string, unknown>; values: FormValues; onChange: (values: FormValues) => void
  onSend: () => void; disabled: boolean; sending: boolean; code: string
}) {
  const form = useRef<HTMLFormElement>(null)
  const fields = schemaFields(schema)
  const primary = fields.filter((field) => ['messages', 'text'].includes(field.name))
  const advanced = fields.filter((field) => !['messages', 'text'].includes(field.name))
  const summary = code === 'long-summary'
  const update = (name: string, value: string) => onChange({ ...values, [name]: value })
  const renderField = (field: typeof fields[number]) => {
    const options = Array.isArray(field.schema.enum) ? field.schema.enum : null
    const multiline = ['messages', 'text'].includes(field.name) || ['array', 'object', 'json'].includes(field.type)
    const askWarn = summary && field.name === 'text' && looksLikeQuestion(values[field.name] ?? '')
    return <Fragment key={field.name}>
      <label className="field schema-field"><span className="field-label">{field.title}{field.required && <span className="schema-required"> *</span>}</span>
        {options || field.type === 'boolean' ? <select className="form-control" value={values[field.name] ?? ''} required={field.required}
          onChange={(e) => update(field.name, e.target.value)}><option value="">请选择</option>{(options ?? [true, false]).map((option) =>
            <option key={String(option)} value={String(option)}>{String(option)}</option>)}</select> : multiline ?
          <textarea className="form-control schema-textarea" rows={field.name === 'text' ? 5 : 3}
            value={values[field.name] ?? ''} required={field.required}
            minLength={field.type === 'string' && typeof field.schema.minLength === 'number' ? field.schema.minLength : undefined}
            maxLength={typeof field.schema.maxLength === 'number' ? field.schema.maxLength : 12000}
            placeholder={field.name === 'messages' ? '输入你的消息，Ctrl + Enter 发送…' : field.name === 'text' ? '将需要提炼摘要的文本粘贴到这里…' : '按输入要求填写 JSON'}
            onKeyDown={(e) => { if ((e.ctrlKey || e.metaKey) && e.key === 'Enter' && !e.nativeEvent.isComposing) { e.preventDefault(); form.current?.requestSubmit() } }}
            onChange={(e) => update(field.name, e.target.value)} /> :
          <input className="form-control" type={['integer', 'number'].includes(field.type) ? 'number' : 'text'}
            value={values[field.name] ?? ''} required={field.required}
            min={typeof field.schema.minimum === 'number' ? field.schema.minimum : undefined}
            max={typeof field.schema.maximum === 'number' ? field.schema.maximum : undefined}
            step={field.type === 'integer' ? 1 : field.type === 'number' ? 'any' : undefined}
            onChange={(e) => update(field.name, e.target.value)} />}
        {field.name === 'text' ? <span className="schema-text-count">{(values[field.name] ?? '').length.toLocaleString()} 字符</span> :
          typeof field.schema.description === 'string' && <span className="field-hint">{field.schema.description}</span>}
      </label>
      {askWarn && <p className="schema-warn" role="status">这段看起来像提问，提交后只会得到它的摘要。需要答案请改用「多轮对话」。</p>}
    </Fragment>
  }
  return <form ref={form} className="schema-form" onSubmit={(e) => { e.preventDefault(); if (!disabled) onSend() }}>
    <fieldset disabled={disabled} className="schema-fieldset">
      {!fields.length && <label className="field"><span className="field-label">输入 JSON</span><textarea className="form-control mono" rows={4} required value={values.__json ?? ''} onChange={(e) => update('__json', e.target.value)} placeholder={'{"text":"待处理的文本"}'} /></label>}
      {summary && <p className="schema-note">{SUMMARY_NOTICE}</p>}
      {primary.map(renderField)}
      {!!advanced.length && <details className="schema-advanced" open={primary.length === 0 || advanced.some((field) => field.required && !(values[field.name] ?? '').trim())}><summary><SlidersHorizontal size={13} />参数设置<span>{advanced.length} 项</span><ChevronDown size={12} /></summary><div className="schema-advanced-fields">{advanced.map(renderField)}</div></details>}
      <div className="schema-form-bottom"><span>Ctrl / ⌘ + Enter 发送 · 降级不计费</span>
        <button type="submit" className="button-primary" disabled={disabled}>{sending ? <LoaderCircle size={14} className="spinner" /> : <Send size={14} />}{sending ? '执行中…' : code === 'long-summary' ? '生成摘要' : '发送消息'}</button></div>
    </fieldset>
  </form>
}
