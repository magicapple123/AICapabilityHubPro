import { createHash, randomBytes } from 'node:crypto'
import { admin, api, assert, evidence, nonce, ok, screenshotJson, sql } from './runtime_support.mjs'

const checks = [], responses = [], queries = {}, results = {}
let stage = 'bootstrap', operator, activeAccount, lockAccount, temporarilyDisabled = false
const check = (name, passed) => checks.push({ name, passed: Boolean(passed) })
const safeResponse = (action, response, expectedCode) => {
  const item = { action, http: response.status, code: response.code, expected_code: expectedCode, request_id: response.requestId }
  responses.push(item)
  check(action, response.status === 200 && response.code === expectedCode)
}
async function registerAccount() {
  const username = 'p14-live-' + nonce(), password = randomBytes(24).toString('hex')
  const registration = await ok('/api/user/register', { method: 'POST', body: { username, password } })
  const userId = Number(registration.user_id)
  assert(Number.isSafeInteger(userId) && userId > 0, 'dedicated acceptance user has no numeric id')
  return { username, password, userId }
}
async function status(value) {
  return ok('/api/user/admin/users/' + activeAccount.userId + '/status', { method: 'PUT', token: operator.token, body: { status: value } })
}

try {
  operator = await admin('p14')
  stage = 'register-and-login'
  activeAccount = await registerAccount()
  lockAccount = await registerAccount()
  const session = await ok('/api/user/login', { method: 'POST', body: { username: activeAccount.username, password: activeAccount.password } })
  const oldToken = session.token
  assert(typeof oldToken === 'string' && oldToken.length > 0, 'dedicated login has no token')
  const routes = ['/api/user/profile', '/api/chat/sessions', '/api/billing/records']
  for (const route of routes) safeResponse('before-disable ' + route, await api(route, { token: oldToken }), 0)

  stage = 'old-jwt-disabled'
  temporarilyDisabled = true
  await status('disabled')
  for (const route of routes) safeResponse('disabled-old-jwt ' + route, await api(route, { token: oldToken }), 1005)
  await status('normal')
  temporarilyDisabled = false
  stage = 'old-jwt-reenabled'
  for (const route of routes) safeResponse('reenabled-old-jwt ' + route, await api(route, { token: oldToken }), 0)

  stage = 'five-failures-and-sixth-lock'
  const incorrectPassword = randomBytes(24).toString('hex')
  for (let attempt = 1; attempt <= 5; attempt++) {
    safeResponse('wrong-password attempt=' + attempt, await api('/api/user/login', { method: 'POST', body: { username: lockAccount.username, password: incorrectPassword } }), 1003)
  }
  safeResponse('sixth-correct-password-still-locked', await api('/api/user/login', { method: 'POST', body: { username: lockAccount.username, password: lockAccount.password } }), 4001)

  stage = 'audit-and-financial-sql'
  const fingerprint = createHash('sha256').update(lockAccount.username.trim().toLowerCase()).digest('hex')
  queries.login_audit = "SELECT id,resource_id,action,operator_id,request_id,after_json FROM user_db.t_operation_log WHERE action='login_failed' AND JSON_UNQUOTE(JSON_EXTRACT(after_json,'$.account_fingerprint'))='" + fingerprint + "' ORDER BY id"
  const auditRows = sql(queries.login_audit, 'aihub-verify-user')
  const reasons = new Set(['invalid_credentials', 'locked', 'disabled'])
  const allowedKeys = new Set(['reason', 'account_fingerprint', 'peer_fingerprint'])
  results.login_audit = auditRows.map(row => {
    const metadata = typeof row.after_json === 'string' ? JSON.parse(row.after_json) : row.after_json
    const keys = metadata && typeof metadata === 'object' ? Object.keys(metadata) : []
    const safe = keys.length === 3 && keys.every(key => allowedKeys.has(key)) && reasons.has(metadata.reason)
      && metadata.account_fingerprint === fingerprint && /^[a-f0-9]{64}$/.test(metadata.peer_fingerprint)
    check('audit-metadata-only id=' + row.id, safe)
    return { id: row.id, resource_id: row.resource_id, action: row.action, operator_id: row.operator_id, request_id: row.request_id,
      metadata_safe: safe, ...(safe ? { metadata } : { unexpected_metadata: true }) }
  })
  check('exactly-six-login-audit-rows', auditRows.length === 6)
  check('sixth-audit-records-locked', results.login_audit.at(-1)?.metadata?.reason === 'locked')
  const ids = [activeAccount.userId, lockAccount.userId].join(',')
  queries.accounts = 'SELECT user_id,balance,frozen,version FROM user_db.t_points_account WHERE user_id IN (' + ids + ') ORDER BY user_id'
  queries.points = "SELECT user_id,biz_type,direction,COUNT(*) AS records,SUM(amount) AS points FROM user_db.t_points_log WHERE user_id IN (" + ids + ') GROUP BY user_id,biz_type,direction ORDER BY user_id'
  queries.billing = 'SELECT user_id,COUNT(*) AS records,COALESCE(SUM(cost),0) AS points FROM billing_db.t_call_record WHERE user_id IN (' + ids + ') GROUP BY user_id'
  results.accounts = sql(queries.accounts, 'aihub-verify-user')
  results.points = sql(queries.points, 'aihub-verify-user')
  results.billing = sql(queries.billing)
  check('both-dedicated-points-accounts-exist', results.accounts.length === 2)
  check('no-billing-created-by-read-or-login', results.billing.length === 0)
  check('only-registration-points-remain', results.points.length === 2 && results.points.every(row => row.biz_type === 'register' && row.direction === 'in' && row.records === 1))
} catch (error) {
  checks.push({ name: 'runtime-exception stage=' + stage, passed: false, error_type: error?.name ?? 'Error' })
} finally {
  if (temporarilyDisabled && operator && activeAccount) {
    try { await status('normal'); check('cleanup-restored-user-normal', true) }
    catch { check('cleanup-restored-user-normal', false) }
  }
}
const passed = checks.length > 0 && checks.every(item => item.passed)
const data = { item: 'P14', result: passed ? 'PASS' : 'FAIL', tested_via: 'isolated acceptance gateway 127.0.0.1:8080',
  note: 'Strict sixth-attempt assertion is retained; process-local multi-worker counters may expose a real deployment failure.',
  stage, user_ids: [activeAccount?.userId, lockAccount?.userId].filter(Boolean), checks, responses, sql: queries, results }
const evidencePath = evidence('P14', data)
let screenshotPath
try { screenshotPath = await screenshotJson('P14', data) }
catch { console.log(JSON.stringify({ item: 'P14', result: 'FAIL', evidence: evidencePath, screenshot_error: true })); process.exitCode = 1 }
console.log(JSON.stringify({ item: 'P14', result: data.result, checks: checks.length, failed: checks.filter(item => !item.passed).map(item => item.name), evidence: evidencePath, screenshot: screenshotPath }))
if (!passed) process.exitCode = 1
