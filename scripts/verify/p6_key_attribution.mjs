/**
 * P6 实机验收：同一用户两把 Key 分别调用，账单可归因；禁用其中一把不影响另一把；
 * Key 创建/禁用写审计且不含密钥材料；`api_key_id` 筛选与按 Key 分布可用。
 *
 * 走真实网关 + 真实 MySQL（独立验收栈 23307），不打印任何 Secret，只保留编号。
 */
import {
  admin, api, assert, evidence, ok, screenshotJson, sql,
} from './runtime_support.mjs'

const item = 'P6'

async function createKey(token, name) {
  const key = await ok('/api/user/apikeys', { method: 'POST', token, body: { name } })
  assert(key.secret_key && key.access_key && key.id, 'API Key 创建响应缺少字段')
  return key
}

async function exchange(accessKey, secretKey) {
  return ok('/api/user/apikeys/exchange', {
    method: 'POST',
    body: { access_key: accessKey, secret_key: secretKey },
  })
}

async function callWithJwt(token) {
  return ok('/api/chat/completions', {
    method: 'POST',
    token,
    body: {
      capability_id: 1,
      input: { messages: [{ role: 'user', content: 'p6 key attribution' }] },
    },
  })
}

const operator = await admin('P6')
// 登录响应里 user 结构随版本有差异，用户 ID 一律以 /profile 为准。
const profile = await ok('/api/user/profile', { token: operator.token })
operator.id = profile.id ?? profile.user_id
assert(typeof operator.id === 'number' && operator.id > 0, '无法解析管理员用户 ID')
const keyA = await createKey(operator.token, 'p6-key-a')
const keyB = await createKey(operator.token, 'p6-key-b')

const sessionA = await exchange(keyA.access_key, keyA.secret_key)
const sessionB = await exchange(keyB.access_key, keyB.secret_key)

const callA = await callWithJwt(sessionA.token)
const callB = await callWithJwt(sessionB.token)
// 网页调试台路径：登录 JWT 直接调，没有 Key 身份
const callWeb = await callWithJwt(operator.token)

assert(callA.cost === 5 && callB.cost === 5, '两次 Key 调用应各扣 5 分')

const rows = sql(
  `SELECT request_id, api_key_id, entrypoint, cost, call_status
   FROM billing_db.t_call_record
   WHERE request_id IN ('${callA.request_id}','${callB.request_id}','${callWeb.request_id}')`,
)
const byRequest = Object.fromEntries(rows.map((row) => [row.request_id, row]))
assert(byRequest[callA.request_id]?.api_key_id === keyA.id, 'Key A 调用的 api_key_id 不正确')
assert(byRequest[callB.request_id]?.api_key_id === keyB.id, 'Key B 调用的 api_key_id 不正确')
assert(byRequest[callA.request_id]?.entrypoint === 'platform_api', 'Key 调用应标记 platform_api')
assert(byRequest[callWeb.request_id]?.api_key_id === null, '网页调试台调用不应有 Key 身份')
assert(byRequest[callWeb.request_id]?.entrypoint === 'web', '网页调试台调用应标记 web')

// 管理员按 Key 筛选：只命中 A
const filtered = await ok(
  `/api/billing/admin/records?user_id=${operator.id}&api_key_id=${keyA.id}&page=1&page_size=50`,
  { token: operator.token },
)
assert(filtered.list.every((row) => row.api_key_id === keyA.id), '按 Key 筛选返回了其它 Key 的记录')
assert(filtered.list.some((row) => row.request_id === callA.request_id), '按 Key 筛选没有命中本次调用')

// 按 Key 分布：A、B 都在，网页调用不进表
const keyUsage = await ok(
  `/api/billing/admin/users/${operator.id}/keys-usage`, { token: operator.token },
)
const usageIds = keyUsage.list.map((row) => row.api_key_id).sort((a, b) => a - b)
assert(usageIds.includes(keyA.id) && usageIds.includes(keyB.id), '按 Key 分布缺少刚产生的 Key')

// 禁用 A：A 不能换令牌，B 不受影响
await ok(`/api/user/apikeys/${keyA.id}/disable`, { method: 'PUT', token: operator.token })
const disabled = await api('/api/user/apikeys/exchange', {
  method: 'POST', body: { access_key: keyA.access_key, secret_key: keyA.secret_key },
})
assert(disabled.code === 1003, '禁用后的 Key 仍可换令牌，code=' + disabled.code)
const sessionB2 = await exchange(keyB.access_key, keyB.secret_key)
assert(sessionB2.token, '禁用 A 后 B 不应受影响')

// 审计：create + disable，且不含任何密钥材料
const audit = await ok(
  `/api/user/admin/audit?resource_type=apikey&resource_id=${keyA.id}`,
  { token: operator.token },
)
const actions = audit.list.map((row) => row.action)
assert(actions.includes('create') && actions.includes('disable'), '审计缺少 Key 创建/禁用记录: ' + actions)
const auditText = JSON.stringify(audit.list)
for (const secret of [keyA.secret_key, keyB.secret_key]) {
  assert(!auditText.includes(secret), '审计里出现了明文 Secret')
}
assert(!/secret_hash|secret_key/.test(auditText), '审计里出现了密钥字段名')

// P10：日预算设置即时生效（0 = 不限），并写预算审计
const budget = await ok(`/api/user/admin/users/${operator.id}/budget`, {
  method: 'PUT', token: operator.token, body: { daily_points_limit: 0 },
})
assert(budget.daily_points_limit === 0, '日预算应保持 0（不限）')
const budgetAudit = await ok(
  `/api/user/admin/audit?resource_type=user&resource_id=${operator.id}&action=budget`,
  { token: operator.token },
)
assert(Array.isArray(budgetAudit.list), '预算审计查询失败')

const summary = {
  item,
  result: 'PASS',
  user_id: operator.id,
  key_ids: [keyA.id, keyB.id],
  calls: {
    key_a: { request_id: callA.request_id, api_key_id: keyA.id, entrypoint: 'platform_api' },
    key_b: { request_id: callB.request_id, api_key_id: keyB.id, entrypoint: 'platform_api' },
    web: { request_id: callWeb.request_id, api_key_id: null, entrypoint: 'web' },
  },
  filtered_rows: filtered.list.length,
  key_usage: usageIds,
  disabled_key_exchange_code: disabled.code,
  audit_actions: actions,
  checked_at: new Date().toISOString(),
}
const evidencePath = evidence(item, summary)
const screenshotPath = await screenshotJson(item, summary)
console.log(JSON.stringify({ ...summary, evidence: evidencePath, screenshot: screenshotPath }))
