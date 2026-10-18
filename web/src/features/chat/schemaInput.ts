/** Pure form/context logic, shared by the browser UI and Node regression tests. */
export interface InputField {
  name: string
  title: string
  type: string
  required: boolean
  schema: Record<string, unknown>
}

export interface ContextTurn {
  role: 'user' | 'assistant'
  content: string
  context: boolean
}

const TITLES: Record<string, string> = {
  messages: '消息', text: '待摘要文本', max_length: '摘要字数上限', temperature: '随机性',
}

export function objectValue(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export function schemaFields(schema: Record<string, unknown>): InputField[] {
  if (!objectValue(schema.properties)) return []
  const required = Array.isArray(schema.required) ? schema.required : []
  return Object.entries(schema.properties).map(([name, value]) => {
    const spec = objectValue(value) ? value : {}
    return { name, title: typeof spec.title === 'string' ? spec.title : TITLES[name] || name,
      type: typeof spec.type === 'string' ? spec.type : 'json', required: required.includes(name), schema: spec }
  })
}

export function initialValues(schema: Record<string, unknown>): Record<string, string> {
  return Object.fromEntries(schemaFields(schema).map((field) => [field.name,
    field.schema.default === undefined ? '' : typeof field.schema.default === 'object'
      ? JSON.stringify(field.schema.default) : String(field.schema.default)]))
}

export function buildInput(
  schema: Record<string, unknown>, values: Record<string, string>,
  context: ContextTurn[], code: string,
): Record<string, unknown> {
  const fields = schemaFields(schema)
  if (!fields.length) {
    const parsed: unknown = JSON.parse(values.__json || '{}')
    if (!objectValue(parsed)) throw new Error('输入必须是 JSON 对象。')
    return parsed
  }
  const result: Record<string, unknown> = {}
  for (const field of fields) {
    const raw = values[field.name] ?? ''
    if (!raw.trim()) {
      if (field.required) throw new Error(`请填写${field.title}。`)
      continue
    }
    if (field.name === 'messages' && code === 'chat-completions') {
      result.messages = [...context.filter((turn) => turn.context).slice(-19)
        .map(({ role, content }) => ({ role, content })), { role: 'user', content: raw.trim() }]
      continue
    }
    let value: unknown = raw
    if (field.type === 'number' || field.type === 'integer') {
      const numeric = Number(raw)
      if (!Number.isFinite(numeric) || (field.type === 'integer' && !Number.isInteger(numeric))) {
        throw new Error(`${field.title}需要有效${field.type === 'integer' ? '整数' : '数字'}。`)
      }
      if (typeof field.schema.minimum === 'number' && numeric < field.schema.minimum)
        throw new Error(`${field.title}不能小于 ${field.schema.minimum}。`)
      if (typeof field.schema.maximum === 'number' && numeric > field.schema.maximum)
        throw new Error(`${field.title}不能大于 ${field.schema.maximum}。`)
      value = numeric
    } else if (field.type === 'boolean') {
      if (raw !== 'true' && raw !== 'false') throw new Error(`${field.title}必须为 true 或 false。`)
      value = raw === 'true'
    } else if (['array', 'object', 'json'].includes(field.type)) {
      value = JSON.parse(raw)
      if (field.type === 'array' && !Array.isArray(value)) throw new Error(`${field.title}必须是数组。`)
      if (field.type === 'object' && !objectValue(value)) throw new Error(`${field.title}必须是对象。`)
    } else if (field.type === 'string') {
      if (typeof field.schema.maxLength === 'number' && raw.length > field.schema.maxLength)
        throw new Error(`${field.title}超过 ${field.schema.maxLength} 字符。`)
      if (typeof field.schema.minLength === 'number' && raw.length < field.schema.minLength)
        throw new Error(`${field.title}至少需要 ${field.schema.minLength} 字符。`)
    }
    if (Array.isArray(field.schema.enum) && !field.schema.enum.includes(value)) {
      throw new Error(`${field.title}不在允许选项中。`)
    }
    result[field.name] = value
  }
  return result
}

export function positiveCapabilityId(raw: string): number | null {
  if (!/^[1-9]\d*$/.test(raw)) return null
  const id = Number(raw)
  return Number.isSafeInteger(id) ? id : null
}
