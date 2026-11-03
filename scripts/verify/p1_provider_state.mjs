import { admin, api, assert, compose, evidence, nonce, ok, screenshotJson, sql } from './runtime_support.mjs'

compose(['up', '-d', '--build', '--no-deps', '--wait', 'ai-chat-service', 'capability-service'])
const operator = await admin('p1')
const suffix = nonce()
const draft = await ok('/api/chat/providers', { method: 'POST', token: operator.token, body: {
  name: 'P1 draft', alias: 'p1-draft-' + suffix, protocol: 'openai-chat', base_url: 'https://api.deepseek.com/v1',
  api_key: 'synthetic-draft-key-not-used', default_model: 'deepseek-flash',
} })
const categories = await ok('/api/capability/categories', { token: operator.token })
const rejected = await api('/api/capability', { method: 'POST', token: operator.token, body: {
  name: 'P1 rejected draft binding', code: 'p1-live-rejected-' + suffix, category_id: (categories.list ?? categories)[0].id,
  service_name: 'ai-chat-service', path: '/api/chat/completions', param_schema: { type: 'object' },
  status: 'online', executor: 'chat', provider_alias: draft.alias, price_per_call: 5,
} })
assert(rejected.code === 2001 && rejected.message.includes('draft') && rejected.message.includes(draft.alias), 'draft binding was not clearly rejected')
const active = sql("SELECT c.id,c.openai_alias,c.provider_alias,p.id AS provider_id FROM capability_db.t_capability c JOIN ai_chat_db.t_model_provider p ON p.alias=c.provider_alias WHERE c.code LIKE 'p11-live-%' AND p.status='enabled' ORDER BY c.id DESC LIMIT 1")[0]
assert(active, 'P11 live provider fixture is required')
const key = await ok('/api/user/apikeys', { method: 'POST', token: operator.token, body: { name: 'P1 temporary verification' } })
const before = sql('SELECT COUNT(*) AS records FROM billing_db.t_call_record WHERE capability_id=' + active.id)[0].records
try {
  await ok('/api/chat/providers/' + active.provider_id + '/status', { method: 'PUT', token: operator.token, body: { status: 'disabled' } })
  const platform = await api('/api/chat/completions', { method: 'POST', token: operator.token, body: { capability_id: active.id, messages: [{ role: 'user', content: 'P1 isolated check' }] } })
  const compat = await api('/v1/chat/completions', { method: 'POST', token: key.secret_key, body: { model: active.openai_alias, messages: [{ role: 'user', content: 'P1 isolated check' }] } })
  assert(platform.code === 2009 && platform.message.includes(active.provider_alias), 'runtime platform provider error mismatch')
  assert(compat.status === 503 && compat.error.type === 'api_error' && compat.error.code === 'platform_2009', 'OpenAI provider error mismatch')
  const query = "SELECT COUNT(*) AS rejected_rows FROM capability_db.t_capability WHERE code='p1-live-rejected-" + suffix + "'"
  const rows = sql(query)
  const after = sql('SELECT COUNT(*) AS records FROM billing_db.t_call_record WHERE capability_id=' + active.id)[0].records
  assert(rows[0].rejected_rows === 0 && before === after, 'rejected request wrote a capability or bill')
  const data = { item: 'P1', draft_save: { code: rejected.code, message: rejected.message }, platform: { code: platform.code, message: platform.message }, compat: { http: compat.status, error: compat.error }, sql: query, rows, bills_before: before, bills_after: after }
  console.log(JSON.stringify({ result: 'PASS', evidence: evidence('P1', data), screenshot: await screenshotJson('P1', data) }))
} finally {
  await ok('/api/chat/providers/' + active.provider_id + '/status', { method: 'PUT', token: operator.token, body: { status: 'enabled' } })
}
