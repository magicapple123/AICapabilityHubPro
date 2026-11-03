import { useState } from 'react'
import { FieldError } from './editorUi'

const SCHEMA_TEMPLATES: Record<'chat' | 'summary', Record<string, unknown>> = {
  chat: {
    type: 'object',
    properties: {
      messages: {
        type: 'array',
        items: {
          type: 'object',
          properties: {
            role: { type: 'string', enum: ['system', 'user', 'assistant'] },
            content: { type: 'string' },
          },
          required: ['role', 'content'],
        },
      },
    },
    required: ['messages'],
  },
  summary: {
    type: 'object',
    properties: {
      text: { type: 'string', maxLength: 12000 },
      max_length: { type: 'integer', minimum: 30, maximum: 1000, default: 200 },
    },
    required: ['text'],
  },
}

/**
 * P9.1/P9.3：模板选择改成标准标签行（标签不折行），并补「格式化」与失焦校验，
 * 错误直接落在 Schema 字段下方而不是只在表单底部。
 */
export function SchemaFields({ value, error, onChange, onValidate }: {
  value: string
  error?: string
  onChange: (value: string) => void
  onValidate: () => void
}) {
  const [template, setTemplate] = useState<'' | 'chat' | 'summary'>('')
  const [note, setNote] = useState('')
  const applyTemplate = (next: '' | 'chat' | 'summary') => {
    setTemplate(next)
    if (!next) return
    onChange(JSON.stringify(SCHEMA_TEMPLATES[next], null, 2))
    setNote(`已填入${next === 'chat' ? '聊天' : '摘要'}模板`)
  }
  const format = () => {
    if (!value.trim()) { setNote('还没有可格式化的内容'); return }
    try {
      onChange(JSON.stringify(JSON.parse(value), null, 2))
      setNote('已格式化')
    } catch {
      setNote('不是合法 JSON，无法格式化')
    }
  }
  return <section className="cap-section">
    <h3 className="cap-section-title">输入 Schema</h3>
    <div className="cap-schema-toolbar">
      <span className="field-label cap-label" id="cap-schema-template-label">Schema 模板</span>
      <select className="form-control cap-schema-template" aria-labelledby="cap-schema-template-label"
        value={template} onChange={(e) => applyTemplate(e.target.value as '' | 'chat' | 'summary')}>
        <option value="">自定义（手动填写）</option>
        <option value="chat">聊天</option>
        <option value="summary">摘要</option>
      </select>
      <button type="button" className="button-secondary cap-schema-action" onClick={format}>格式化</button>
      {note && <span className="field-hint cap-inline-note" role="status">{note}</span>}
    </div>
    <textarea className="form-control mono cap-schema-input" rows={8} spellCheck={false} value={value}
      aria-label="输入 Schema" placeholder={'{"type":"object","properties":{}}'}
      onChange={(e) => { onChange(e.target.value); setNote('') }} onBlur={onValidate} />
    <FieldError message={error} />
    <p className="field-hint">仅支持对象根类型的内联 Schema，不支持 $ref、$dynamicRef、$recursiveRef 或 $id；实际执行仍会按该 Schema 校验参数。</p>
  </section>
}
