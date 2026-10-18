import { LoaderCircle, Send } from 'lucide-react'
import { schemaFields } from './schemaInput'
import type { FormValues } from './types'

const CONTROL = 'w-full rounded-xl border border-white/15 bg-[#11130f] px-4 py-3 text-sm text-white outline-none focus:border-[#c9f05b] disabled:opacity-50'

export function SchemaForm({ schema, values, onChange, onSend, disabled, sending, code }: {
  schema: Record<string, unknown>; values: FormValues; onChange: (values: FormValues) => void
  onSend: () => void; disabled: boolean; sending: boolean; code: string
}) {
  const fields = schemaFields(schema)
  const update = (name: string, value: string) => onChange({ ...values, [name]: value })
  return (
    <form onSubmit={(event) => { event.preventDefault(); onSend() }} className="space-y-5 border-t border-white/10 p-6">
      <fieldset disabled={disabled} className="min-w-0 space-y-4 disabled:opacity-60">
        {!fields.length && (
          <label className="block text-sm text-white/70">输入 JSON
            <textarea className={`${CONTROL} mt-2 font-mono`} rows={6} value={values.__json ?? ''}
              onChange={(event) => update('__json', event.target.value)} placeholder={'{"text":"待处理的文本"}'} />
          </label>
        )}
        {fields.map((field) => {
          const options = Array.isArray(field.schema.enum) ? field.schema.enum : null
          const multiline = field.name === 'messages' || field.type === 'string' || ['object', 'array', 'json'].includes(field.type)
          return (
            <label key={field.name} className="block text-sm text-white/70">
              <span>{field.title}{field.required && <span className="ml-1 text-[#c9f05b]">*</span>}</span>
              {options || field.type === 'boolean' ? (
                <select className={`${CONTROL} mt-2`} value={values[field.name] ?? ''}
                  onChange={(event) => update(field.name, event.target.value)} required={field.required}>
                  <option value="">请选择</option>
                  {(options ?? [true, false]).map((option) => <option key={String(option)} value={String(option)}>{String(option)}</option>)}
                </select>
              ) : multiline ? (
                <textarea className={`${CONTROL} mt-2 resize-y`} rows={field.name === 'text' ? 6 : 3}
                  value={values[field.name] ?? ''} required={field.required}
                  maxLength={typeof field.schema.maxLength === 'number' ? field.schema.maxLength : 12000}
                  placeholder={field.name === 'messages' ? '输入本轮消息，已有对话会自动作为上下文。' : undefined}
                  onChange={(event) => update(field.name, event.target.value)} />
              ) : (
                <input className={`${CONTROL} mt-2`} type={['integer', 'number'].includes(field.type) ? 'number' : 'text'}
                  value={values[field.name] ?? ''} required={field.required}
                  min={typeof field.schema.minimum === 'number' ? field.schema.minimum : undefined}
                  max={typeof field.schema.maximum === 'number' ? field.schema.maximum : undefined}
                  step={field.type === 'integer' ? 1 : 'any'}
                  onChange={(event) => update(field.name, event.target.value)} />
              )}
              {typeof field.schema.description === 'string' && <span className="mt-1 block text-xs text-white/40">{field.schema.description}</span>}
            </label>
          )
        })}
        <button type="submit" disabled={disabled} className="flex items-center gap-2 rounded-xl bg-[#c9f05b] px-5 py-3 text-sm font-medium text-[#11130f] disabled:cursor-not-allowed disabled:opacity-40">
          {sending ? <LoaderCircle size={16} className="animate-spin" /> : <Send size={16} />}
          {sending ? '执行中…' : code === 'long-summary' ? '生成摘要' : '发送消息'}
        </button>
      </fieldset>
      <p className="text-xs leading-5 text-white/35">服务端会重新读取最新状态、Schema 和价格。真实模型故障会降级，本次不计费。</p>
    </form>
  )
}
