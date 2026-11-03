/**
 * P8：可执行性判断的唯一口径。
 *
 * 后端（D2）已把"能不能执行"从 `code` 迁到 `executor`，`/api/chat/executors`
 * 的 `codes` 只是旧前端兼容字段。前端三处判断（市场卡片/详情、调试台、登记表单）
 * 必须共用本模块，否则会出现"市场说没执行器、后端其实能跑"的半迁移状态。
 */

/** 与 ai-chat-service `EXECUTORS[*].legacy_codes` 一致；仅用于旧数据（executor 为空）。 */
export const CODE_TO_EXECUTOR: Readonly<Record<string, string>> = {
  'chat-completions': 'chat',
  'long-summary': 'summary',
  'text-to-image': 'image-generate',
}

/** `/api/chat/executors` 中本模块使用的部分；`executor_protocols` 仅新后端返回。 */
export interface ExecutorCatalogView {
  codes?: string[]
  executors?: string[]
  executor_protocols?: Record<string, string[]>
}

/** 执行器 → 协议白名单的兜底，与 capability-service `EXECUTOR_PROTOCOLS` 一致。 */
const FALLBACK_PROTOCOLS: Readonly<Record<string, readonly string[]>> = {
  chat: ['openai-chat', 'openai-responses'],
  summary: ['openai-chat', 'openai-responses'],
  'image-generate': ['openai-image', 'dashscope-image'],
  embedding: ['openai-embedding'],
}

/** 登记表单可选的执行器；与后端 `Executor` 枚举同值。 */
export const EXECUTOR_OPTIONS: ReadonlyArray<{ value: string; label: string }> = [
  { value: 'chat', label: 'chat · 多轮对话' },
  { value: 'summary', label: 'summary · 长文摘要' },
  { value: 'image-generate', label: 'image-generate · 文生图' },
]

/** 必须绑定供应商别名的执行器（后端 `validate_executor` 同口径）。 */
export function requiresProvider(executor: string): boolean {
  return executor === 'image-generate' || executor === 'embedding'
}

/** 优先用库里的 executor；为空时按旧 code 反查，避免历史数据被判成不可执行。 */
export function resolveExecutor(capability: { executor?: string | null; code?: string }): string {
  const explicit = (capability.executor ?? '').trim()
  if (explicit) return explicit
  const code = (capability.code ?? '').trim()
  return CODE_TO_EXECUTOR[code] ?? ''
}

/**
 * 已接入的执行器列表；`null` 表示目录还没拿到（加载中或请求失败），此时不做断言。
 */
export function supportedExecutors(catalog: ExecutorCatalogView | null | undefined): string[] | null {
  if (!catalog) return null
  if (catalog.executors) return catalog.executors
  if (!catalog.codes) return null
  const derived = new Set<string>()
  for (const code of catalog.codes) {
    const executor = CODE_TO_EXECUTOR[code]
    if (executor) derived.add(executor)
  }
  return [...derived]
}

export function isExecutorSupported(
  catalog: ExecutorCatalogView | null | undefined,
  executor: string,
): boolean {
  if (!executor) return false
  return supportedExecutors(catalog)?.includes(executor) ?? false
}

/**
 * 该执行器允许的供应商协议。
 *
 * 取「目录返回的 executor_protocols」与「本地兜底（= 保存阶段的权威表
 * capability-service `EXECUTOR_PROTOCOLS`）」的并集：
 * `/api/chat/executors` 的 executor_protocols 只列执行器实际实现的协议
 * （chat 只有 openai-chat），而保存时 chat 也允许 openai-responses，
 * 单用前者会把合法组合误判成不匹配、拦住保存。
 */
export function executorProtocols(
  catalog: ExecutorCatalogView | null | undefined,
  executor: string,
): string[] {
  const allowed = new Set<string>(FALLBACK_PROTOCOLS[executor] ?? [])
  for (const protocol of catalog?.executor_protocols?.[executor] ?? []) allowed.add(protocol)
  return [...allowed]
}

/** 供应商协议是否匹配执行器；协议缺失或白名单为空时不做判定（交后端 2001）。 */
export function protocolMatches(
  catalog: ExecutorCatalogView | null | undefined,
  executor: string,
  protocol: string,
): boolean {
  if (!executor || !protocol) return true
  const allowed = executorProtocols(catalog, executor)
  if (allowed.length === 0) return true
  return allowed.includes(protocol)
}
