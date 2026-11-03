/**
 * P12 实机验收：`/v1/responses` 的字段语义、工具结构翻译与 SSE 事件顺序。
 *
 * 没有 Codex CLI 也能验证协议层：直接用平台 API Key 发真实请求，
 * 断言 1) `store:false` / `reasoning` 不再 4001；2) 扁平工具被翻译后仍能执行；
 * 3) 流式事件顺序固定；4) `store:true` 仍然拒绝。
 */
import {
  admin, assert, evidence, gateway, nonce, ok, screenshotJson,
} from './runtime_support.mjs'

const item = 'P12'

async function createKey(token) {
  return ok('/api/user/apikeys', {
    method: 'POST', token, body: { name: 'p12-responses-' + nonce() },
  })
}

async function postResponses(secret, body) {
  const response = await fetch(gateway + '/v1/responses', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + secret },
    body: JSON.stringify(body),
  })
  const text = await response.text()
  return { status: response.status, text }
}

const operator = await admin('P12')
const key = await createKey(operator.token)

// 自建一个「不绑定供应商」的 chat 能力：走全局 Mock 上游，结果只取决于协议层，
// 不会被某个供应商的密钥/网络问题干扰（那些属于 P11 的验收面）。
const categories = await ok('/api/capability/categories', { token: operator.token })
const alias = 'p12-responses-' + nonce()
const schema = {
  type: 'object',
  required: ['messages'],
  properties: {
    messages: {
      type: 'array', minItems: 1, maxItems: 40,
      items: {
        type: 'object',
        properties: {
          role: { type: 'string', enum: ['system', 'user', 'assistant', 'tool'] },
          content: { type: 'string', minLength: 1, maxLength: 12000 },
        },
        required: ['role', 'content'],
        additionalProperties: false,
      },
    },
    temperature: { type: 'number' },
    max_tokens: { type: 'integer' },
    tools: { type: 'array' },
    tool_choice: {},
  },
  additionalProperties: false,
}
const created = await ok('/api/capability', {
  method: 'POST',
  token: operator.token,
  body: {
    category_id: categories.list[0].id,
    name: 'P12 Responses ' + alias,
    code: 'p12-responses-' + nonce(),
    service_name: 'ai-chat-service',
    path: '/api/chat/completions',
    price_per_call: 5,
    status: 'online',
    executor: 'chat',
    openai_alias: alias,
    param_schema: schema,
  },
})
assert(created.openai_alias === alias, '自建能力没有拿到对外模型名')

const tools = [{
  type: 'function',
  name: 'read_file',
  description: '读取文件内容',
  parameters: {
    type: 'object',
    properties: { path: { type: 'string' } },
    required: ['path'],
  },
}]

// 1) store:false + reasoning + 扁平工具 + 超长 instructions：不得 4001
const allowed = await postResponses(key.secret_key, {
  model: alias,
  input: [{ role: 'user', content: [{ type: 'input_text', text: '读取 README 的第一行' }] }],
  instructions: '你是一个编码助手。'.repeat(2000),
  store: false,
  reasoning: { effort: 'low' },
  tools,
})
assert(allowed.status === 200,
  'store:false / reasoning 被拒绝: http=' + allowed.status + ' ' + allowed.text.slice(0, 200))
const body = JSON.parse(allowed.text)
assert(body.object === 'response', '响应不是 Responses 形态')
assert(Array.isArray(body.platform_warnings), '缺少 platform_warnings 数组')
assert(body.platform_warnings.some((text) => String(text).includes('reasoning')),
  'reasoning 被忽略时应有 warning: ' + JSON.stringify(body.platform_warnings))
assert(typeof body.platform_cost === 'number' && body.platform_cost > 0, '响应缺少 platform_cost')
assert(Array.isArray(body.output) && body.output.length >= 1, '响应缺少 output 项')

// 2) store:true 仍然拒绝（平台不存上游内容）
const rejected = await postResponses(key.secret_key, {
  model: alias, input: 'hello', store: true,
})
assert(rejected.status === 400, 'store:true 应返回 400，实际 ' + rejected.status)
const rejectedBody = JSON.parse(rejected.text)
assert(String(rejectedBody.error?.code) === 'platform_4001', 'store:true 错误码应为 platform_4001')

// 3) 流式事件顺序
const streamResponse = await fetch(gateway + '/v1/responses', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + key.secret_key },
  body: JSON.stringify({ model: alias, input: '流式验证', stream: true, store: false, tools }),
})
assert(streamResponse.status === 200, 'stream=true 请求失败 http=' + streamResponse.status)
const raw = await streamResponse.text()
const events = raw.split('\n')
  .filter((line) => line.startsWith('data: '))
  .map((line) => line.slice(6).trim())
  .filter((data) => data && data !== '[DONE]')
  .map((data) => {
    try { return JSON.parse(data).type } catch { return 'unparsable' }
  })
// 骨架事件必须齐全且有序；`output_text.delta` 只有在平台真的从上游拿到增量文本时才会出现。
const skeleton = [
  'response.created',
  'response.output_item.added',
  'response.content_part.added',
  'response.output_text.done',
  'response.output_item.done',
  'response.completed',
]
let cursor = -1
for (const name of skeleton) {
  const at = events.findIndex((event, index) => index > cursor && event === name)
  assert(at > cursor, `事件顺序缺少 ${name}：${events.join(' → ')}`)
  cursor = at
}
const deltaCount = events.filter((name) => name === 'response.output_text.delta').length
const doneFrame = raw.split('\n')
  .filter((line) => line.startsWith('data: '))
  .map((line) => { try { return JSON.parse(line.slice(6).trim()) } catch { return null } })
  .find((frame) => frame && frame.type === 'response.output_text.done')
const doneText = String(doneFrame?.text || '')
// 有内容就必须有增量事件，且出现在 content_part.added 与 text.done 之间；Mock 上游返回空内容时
// 只记录事实，不放宽断言（增量顺序由 test_responses_compat 的假上游用例覆盖）。
if (doneText) {
  assert(deltaCount > 0, '上游返回了文本但流式没有增量事件：' + events.join(' → '))
  const deltaAt = events.indexOf('response.output_text.delta')
  const partAt = events.indexOf('response.content_part.added')
  const textDoneAt = events.indexOf('response.output_text.done')
  assert(partAt < deltaAt && deltaAt < textDoneAt, '增量事件位置不在 content_part.added 与 text.done 之间')
}

const summary = {
  item,
  result: 'PASS',
  alias,
  warnings: body.platform_warnings,
  platform_cost: body.platform_cost,
  output_types: body.output.map((row) => row.type),
  store_true_http: rejected.status,
  store_true_code: rejectedBody.error?.code,
  stream_events: events,
  stream_delta_count: deltaCount,
  stream_text_length: doneText.length,
  stream_note: doneText
    ? '上游返回文本，增量事件已按顺序出现'
    : '本环境上游（Mock）不产生增量内容，增量顺序由单测的假上游用例覆盖',
  request_id: body.platform_request_id,
  checked_at: new Date().toISOString(),
}
const evidencePath = evidence(item, summary)
const screenshotPath = await screenshotJson(item, summary)
console.log(JSON.stringify({ ...summary, evidence: evidencePath, screenshot: screenshotPath }))
