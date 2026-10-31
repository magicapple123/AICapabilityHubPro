/**
 * 文本摘要能力的界面提示文案与判定工具。
 *
 * 摘要执行器会把用户输入整体作为「待概括材料」处理，并强制拼接系统提示词，
 * 因此这里提供纯函数用于判断输入是否看起来像提问，供界面做出软提示。
 * 本文件不引入任何依赖，便于在 node:test 中直接测试。
 */

/** 摘要能力下常驻展示的说明文案。 */
export const SUMMARY_NOTICE = '只输出摘要，不回答问题；需要问答请切换「多轮对话」能力。'

/** 超过该字符数的输入视为文档材料，即使内部夹带问句也不提示（避免长文档误报）。 */
const QUESTION_MAX_CHARS = 120

/** 疑问标志词：命中任意一个即认为输入带有提问意图。 */
const QUESTION_MARKERS: readonly string[] = [
  '怎么', '如何', '为什么', '为何', '是什么', '什么是',
  '能不能', '可不可以', '是否', '多少', '哪个', '哪些', '哪里', '吗', '呢', '请问',
]

/**
 * 判断一段文本是否看起来像提问。
 *
 * 判定顺序（与产品定义保持一致）：
 * 1. 去除首尾空白后为空 → false；
 * 2. 字符数超过 120 → false（长文档里夹带问句不报警）；
 * 3. 以 `？` 或 `?` 结尾 → true；
 * 4. 命中任一疑问标志词 → true。
 *
 * 实现只使用一次遍历 + 字符串包含判断，不含正则，避免回溯开销。
 *
 * @param text 用户输入的原始文本。
 * @returns 形如提问时返回 true，否则返回 false。
 */
export function looksLikeQuestion(text: string): boolean {
  if (typeof text !== 'string') return false
  const trimmed = text.trim()
  if (!trimmed) return false
  // 按 Unicode 码点计数，避免代理对（如 emoji）被算成两个字符。
  if (Array.from(trimmed).length > QUESTION_MAX_CHARS) return false
  if (trimmed.endsWith('？') || trimmed.endsWith('?')) return true
  return QUESTION_MARKERS.some((marker) => trimmed.includes(marker))
}
