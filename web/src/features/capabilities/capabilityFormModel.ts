import type {
  BillingMode,
  CapabilityManageItem,
  CapabilityStatus,
  CapabilityWritableFields,
} from '@/api/capability'
import {
  executorProtocols,
  protocolMatches,
  requiresProvider,
  resolveExecutor,
  type ExecutorCatalogView,
} from './executorResolver'

/** P9.2：服务名/调用路径是兼容字段，默认预填后端惯用值。 */
export const DEFAULT_SERVICE_NAME = 'ai-chat-service'
export const DEFAULT_PATH = '/api/chat/completions'

const PRICE_MAX = 1_000_000
const MAX_OUTPUT_TOKENS_LIMIT = 32_768
const SCHEMA_MAX_BYTES = 32_768
const FORBIDDEN_SCHEMA_KEYS = ['$ref', '$dynamicRef', '$recursiveRef', '$id']

export type CapabilityFieldKey =
  | 'name' | 'code' | 'category' | 'openai_alias' | 'executor' | 'provider'
  | 'max_output_tokens' | 'price' | 'unit' | 'schema' | 'service' | 'path'

export type FieldErrors = Partial<Record<CapabilityFieldKey, string>>

const FIELD_LABELS: Record<CapabilityFieldKey, string> = {
  name: '能力名称', code: '能力编码', category: '所属分类', openai_alias: '对外模型名',
  executor: '执行器', provider: '供应商', max_output_tokens: '输出上限', price: '计价',
  unit: '计价单位', schema: '输入 Schema', service: '服务名', path: '调用路径',
}

/** 表单态一律用字符串，提交时再转数字，避免 `Number('')` 这类静默 0。 */
export interface CapabilityFormState {
  name: string
  code: string
  openai_alias: string
  category_id: string
  description: string
  schema: string
  billing_mode: BillingMode
  price_per_call: string
  price_per_1k_input: string
  price_per_1k_output: string
  price_per_unit: string
  unit: string
  executor: string
  provider_alias: string
  max_output_tokens: string
  exposed_to_market: boolean
  status: CapabilityStatus
  service_name: string
  path: string
}

export function initialForm(item: CapabilityManageItem | null): CapabilityFormState {
  return {
    name: item?.name ?? '',
    code: item?.code ?? '',
    openai_alias: item?.openai_alias ?? '',
    category_id: item ? String(item.category_id) : '',
    description: item?.description ?? '',
    schema: item?.param_schema ? JSON.stringify(item.param_schema, null, 2) : '',
    billing_mode: item?.billing_mode ?? 'per_call',
    price_per_call: String(item?.price_per_call ?? 0),
    price_per_1k_input: String(item?.price_per_1k_input ?? 0),
    price_per_1k_output: String(item?.price_per_1k_output ?? 0),
    price_per_unit: String(item?.price_per_unit ?? 0),
    unit: item?.unit ?? '',
    // 旧数据 executor 为空时用 code 回退，保存即完成字段迁移；
    // 新建默认 chat，与后端 `CapabilityCreateRequest.executor` 的缺省值一致。
    executor: item ? resolveExecutor(item) : 'chat',
    provider_alias: item?.provider_alias ?? '',
    max_output_tokens: String(item?.max_output_tokens ?? 1024),
    exposed_to_market: item?.exposed_to_market ?? true,
    status: 'draft',
    service_name: item?.service_name || DEFAULT_SERVICE_NAME,
    path: item?.path || DEFAULT_PATH,
  }
}

/** 表单字段改动能精确定位到哪一块错误，避免"改一处清空全部提示"。 */
const FIELD_OF: Readonly<Record<keyof CapabilityFormState, CapabilityFieldKey>> = {
  name: 'name', code: 'code', openai_alias: 'openai_alias', category_id: 'category',
  description: 'name', schema: 'schema', billing_mode: 'price',
  price_per_call: 'price', price_per_1k_input: 'price', price_per_1k_output: 'price',
  price_per_unit: 'price', unit: 'unit', executor: 'executor', provider_alias: 'provider',
  max_output_tokens: 'max_output_tokens', exposed_to_market: 'name', status: 'name',
  service_name: 'service', path: 'path',
}

export function fieldKeyOf(key: keyof CapabilityFormState): CapabilityFieldKey {
  return FIELD_OF[key]
}

/** 与目录服务的结构约束一致；最终仍以服务端校验为准（4002 会覆盖这里）。 */
export function schemaProblem(schema: Record<string, unknown>): string {
  if (schema.type !== 'object') return 'Schema 根类型必须为 object，暂不支持其他根类型。'
  if (new TextEncoder().encode(JSON.stringify(schema)).length > SCHEMA_MAX_BYTES) {
    return 'Schema 序列化后不能超过 32768 字节。'
  }
  const visit = (value: unknown, depth: number): string => {
    if (depth > 20) return 'Schema 嵌套层级不能超过 20 层。'
    if (Array.isArray(value)) {
      for (const child of value) { const problem = visit(child, depth + 1); if (problem) return problem }
      return ''
    }
    if (!value || typeof value !== 'object') return ''
    for (const [key, child] of Object.entries(value)) {
      if (FORBIDDEN_SCHEMA_KEYS.includes(key)) return 'Schema 不能使用 $ref、$dynamicRef、$recursiveRef 或 $id。'
      const problem = visit(child, depth + 1); if (problem) return problem
    }
    return ''
  }
  return visit(schema, 0)
}

/** 失焦即校验（P9.3）：返回问题描述，合法时返回 undefined。 */
export function checkSchemaText(text: string): string | undefined {
  if (!text.trim()) return undefined
  let parsed: unknown
  try { parsed = JSON.parse(text) } catch (cause) {
    return 'Schema 不是合法 JSON：' + (cause instanceof Error ? cause.message : '请检查括号与引号')
  }
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) return 'Schema 必须是 JSON 对象。'
  return schemaProblem(parsed as Record<string, unknown>) || undefined
}

function toInt(raw: string): number | null {
  const text = raw.trim()
  if (!/^\d+$/.test(text)) return null
  const value = Number(text)
  return Number.isSafeInteger(value) ? value : null
}

export interface ProviderOption {
  alias: string
  protocol: string
  status: string
}

export interface ValidationInput {
  form: CapabilityFormState
  /** `/api/chat/executors` 目录，用于取 executor_protocols；缺省时用本地兜底表。 */
  catalog?: ExecutorCatalogView | null
  /** 已接入执行器；null 表示目录未就绪，不做断言。 */
  supported: string[] | null
  /** 供应商清单；null 表示无权限或未加载，协议与状态只提示不拦截。 */
  providers: ProviderOption[] | null
}

export interface ValidationResult {
  errors: FieldErrors
  schema: Record<string, unknown> | null
}

export function validateCapabilityForm(input: ValidationInput): ValidationResult {
  const { form, catalog, supported, providers } = input
  const errors: FieldErrors = {}

  if (!form.name.trim()) errors.name = '请填写能力名称。'
  const code = form.code.trim()
  if (!code) errors.code = '请填写能力编码。'
  else if (!/^[a-z0-9][a-z0-9-]*$/.test(code)) errors.code = '编码只能包含小写字母、数字和连字符，且以字母或数字开头。'
  if (!form.category_id) errors.category = '请选择所属分类。'
  if (form.openai_alias.trim() && !/^[a-z][a-z0-9._-]{1,63}$/.test(form.openai_alias.trim())) {
    errors.openai_alias = '需以小写字母开头，只允许小写字母、数字、点、下划线和连字符。'
  }

  if (!form.executor) errors.executor = '请选择执行器；未选择时该能力无法执行。'
  else if (supported && !supported.includes(form.executor)) {
    errors.executor = `后端尚未接入 ${form.executor} 执行器，保存后调用会返回 2008。`
  }

  const alias = form.provider_alias.trim()
  if (!alias) {
    if (requiresProvider(form.executor)) errors.provider = `${form.executor} 执行器必须绑定供应商别名。`
  } else if (providers) {
    const provider = providers.find((item) => item.alias === alias)
    if (!provider) errors.provider = '未找到该供应商，请先在「模型服务」创建并启用。'
    else if (provider.status !== 'enabled') errors.provider = `供应商 ${alias} 当前为 ${provider.status}，启用前保存会被后端拒绝（2001）。`
    else if (!protocolMatches(catalog, form.executor, provider.protocol)) {
      errors.provider = `执行器 ${form.executor} 只接受 ${executorProtocols(catalog, form.executor).join(' / ')} 协议的供应商，${alias} 是 ${provider.protocol}。`
    }
  }

  const maxTokens = toInt(form.max_output_tokens)
  if (maxTokens === null || maxTokens < 1 || maxTokens > MAX_OUTPUT_TOKENS_LIMIT) {
    errors.max_output_tokens = '输出上限需为 1–32768 的整数。'
  }

  const perCall = toInt(form.price_per_call)
  const perInput = toInt(form.price_per_1k_input)
  const perOutput = toInt(form.price_per_1k_output)
  const perUnit = toInt(form.price_per_unit)
  const badNumber = [perCall, perInput, perOutput, perUnit].some((value) => value !== null && value > PRICE_MAX)
  if (badNumber) errors.price = '积分单价需为 0–1000000 的整数。'
  else if (form.billing_mode === 'per_call' && perCall === null) errors.price = '每次调用积分需为 0–1000000 的整数。'
  else if (form.billing_mode === 'per_token') {
    if (perInput === null || perOutput === null) errors.price = '按 token 单价的格式需为 0–1000000 的整数。'
    else if (perInput <= 0 && perOutput <= 0) errors.price = '按 token 计价时，输入或输出单价至少一项需大于 0。'
  } else if (form.billing_mode === 'per_unit') {
    if (perUnit === null || perUnit <= 0) errors.price = '按件计价的单价需为大于 0 的整数。'
    if (!form.unit.trim()) errors.unit = '按件计价必须填写计价单位，如「张」。'
  }

  if (!form.service_name.trim()) errors.service = '服务名不能为空（默认 ai-chat-service）。'
  if (!form.path.trim().startsWith('/')) errors.path = '调用路径需以 / 开头（默认 /api/chat/completions）。'

  let schema: Record<string, unknown> | null = null
  const schemaText = checkSchemaText(form.schema)
  if (schemaText) errors.schema = schemaText
  else if (form.schema.trim()) schema = JSON.parse(form.schema) as Record<string, unknown>

  return { errors, schema }
}

/** 计价字段按模式归一：后端要求非当前模式的价格为 0，避免"半套价格"。 */
export function buildPayload(
  form: CapabilityFormState,
  schema: Record<string, unknown> | null,
): CapabilityWritableFields {
  const mode = form.billing_mode
  const num = (raw: string) => toInt(raw) ?? 0
  return {
    category_id: Number(form.category_id),
    name: form.name.trim(),
    code: form.code.trim(),
    openai_alias: form.openai_alias.trim() || null,
    service_name: form.service_name.trim(),
    path: form.path.trim(),
    param_schema: schema,
    description: form.description.trim(),
    billing_mode: mode,
    price_per_call: mode === 'per_call' ? num(form.price_per_call) : 0,
    price_per_1k_input: mode === 'per_token' ? num(form.price_per_1k_input) : 0,
    price_per_1k_output: mode === 'per_token' ? num(form.price_per_1k_output) : 0,
    price_per_unit: mode === 'per_unit' ? num(form.price_per_unit) : 0,
    unit: mode === 'per_unit' ? form.unit.trim() : '',
    executor: form.executor,
    provider_alias: form.provider_alias.trim(),
    max_output_tokens: num(form.max_output_tokens),
    exposed_to_market: form.exposed_to_market,
  }
}

export function summarizeErrors(errors: FieldErrors): string {
  const keys = Object.keys(errors) as CapabilityFieldKey[]
  if (keys.length === 0) return ''
  // 底部汇总 = 字段清单 + **全部**问题原文。只放"首个问题"会让长表单里
  // 排在后面的错误（如 Schema）在底部不可见——浏览器验收等的就是它的原文。
  const messages = keys.map((key) => `${FIELD_LABELS[key]}：${errors[key]}`)
  return `${keys.length} 项需要修正：${messages.join('；')}`
}

/** 表单里"编码→执行器"的提示口径（P8.6）：不再写死"会返回 2008"。 */
export function executorHint(
  form: CapabilityFormState,
  supported: string[] | null,
): { text: string; tone: 'idle' | 'ready' | 'warn' } {
  // 该提示挂在「能力编码」下方，编码还没填时先不输出结论。
  if (!form.code.trim()) return { text: '', tone: 'idle' }
  if (!form.executor) return { text: '尚未选择执行器：保存后该能力只能展示，调用会失败。', tone: 'warn' }
  if (supported === null) return { text: `正在确认执行器 ${form.executor} 是否已接入…`, tone: 'idle' }
  if (supported.includes(form.executor)) return { text: `执行器 ${form.executor} 已接入：登记后可在调试台直接执行。`, tone: 'ready' }
  return { text: `执行器 ${form.executor} 尚未接入：保存后调用会返回 2008。`, tone: 'warn' }
}
