import { admin, assert, compose, evidence, nonce, ok, readEnv, runtimeConfig, screenshotJson, sql } from './runtime_support.mjs'

const source = readEnv('services/ai-chat-service/.env')
const suffix = nonce(), outputs = []
compose(['up', '-d', '--build', '--no-deps', '--wait', 'ai-chat-service'], {
  PROVIDER_ALLOWED_HOSTS: 'api.deepseek.com,dashscope.aliyuncs.com',
})
const operator = await admin('p11')
const categories = await ok('/api/capability/categories', { token: operator.token })
const categoryId = (categories.list ?? categories)[0].id
try {
  for (const model of ['deepseek-flash', 'deepseek-v4-pro']) {
    const provider = await ok('/api/chat/providers', { method: 'POST', token: operator.token, body: {
      name: 'P11 ' + model, alias: 'p11-' + model + '-' + suffix, protocol: 'openai-chat',
      base_url: source.MODEL_BASE_URL, api_key: source.MODEL_API_KEY, default_model: model, timeout_ms: 30000,
    } })
    const probe = await ok('/api/chat/providers/' + provider.id + '/test', { method: 'POST', token: operator.token })
    assert(probe.ok, 'provider probe failed model=' + model + ' reason=' + probe.reason)
    await ok('/api/chat/providers/' + provider.id + '/status', { method: 'PUT', token: operator.token, body: { status: 'enabled' } })
    const capability = await ok('/api/capability', { method: 'POST', token: operator.token, body: {
      name: 'P11 ' + model, code: 'p11-live-' + model + '-' + suffix, category_id: categoryId,
      service_name: 'ai-chat-service', path: '/api/chat/completions', description: 'P11 model routing acceptance',
      param_schema: { type: 'object' }, status: 'online', executor: 'chat', provider_alias: provider.alias,
      billing_mode: 'per_call', price_per_call: 5, openai_alias: 'p11-' + model + '-' + suffix, max_output_tokens: 128, exposed_to_market: true,
    } })
    outputs.push({ provider_id: provider.id, provider_alias: provider.alias, expected_model: model, capability_id: capability.id })
  }
  await runtimeConfig({ use_mock: false, model_base_url: source.MODEL_BASE_URL, model_api_key: source.MODEL_API_KEY })
  for (const output of outputs) {
    for (let i = 0; i < 2; i++) {
      const result = await ok('/api/chat/completions', { method: 'POST', token: operator.token, body: { capability_id: output.capability_id, messages: [{ role: 'user', content: 'Reply with OK only.' }] } })
      assert(result.call_status === 'success' && !result.mock && result.cost > 0, 'real generation failed provider=' + output.provider_alias)
      output.calls ??= []
      output.calls.push({ model_name: result.model_name, cost: result.cost, record_id: result.record_id, request_id: result.request_id })
    }
  }
  const ids = outputs.map(x => x.capability_id).join(',')
  const query = 'SELECT capability_id,model_name,call_status,COUNT(*) AS records,SUM(cost) AS points FROM billing_db.t_call_record WHERE capability_id IN (' + ids + ') GROUP BY capability_id,model_name,call_status'
  const rows = sql(query)
  assert(rows.length === 2 && rows.every(x => x.call_status === 'success' && x.records === 2 && Number(x.points) === 10), 'billing model distribution mismatch')
  const data = { item: 'P11', mode: 'real upstream HTTP, two bound provider configurations using two DeepSeek models', limitation: 'Qwen credential is not supplied; cross-vendor Qwen verification remains unverified.', outputs, sql: query, rows }
  console.log(JSON.stringify({ result: 'PASS', rows, evidence: evidence('P11', data), screenshot: await screenshotJson('P11', data) }))
} finally { await runtimeConfig({ use_mock: true }) }
