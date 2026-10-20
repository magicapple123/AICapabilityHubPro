/** Real Settings flows; Secret/JWT values live only in memory, never evidence. */
import assert from 'node:assert/strict'
import { Buffer } from 'node:buffer'
import path from 'node:path'
import type { Page, Request } from 'playwright'
import { assertSecretAbsent, record, records, request, responseFor, result, shanghaiDate, submit, viewport } from './member-browser-support.ts'

export async function runSettingsScenarios(page: Page, base: string, directory: string, checks: string[]) {
  console.log('Browser phase: real Settings')
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto(base + '/settings?tab=profile')
  await page.getByText('普通用户', { exact: true }).waitFor()
  const profile = record((await request(page, 'GET', '/api/user/profile')).body.data)
  assert.equal(profile.role, 'user')
  const nickname = 'QA验收-' + Date.now().toString(36)
  await page.getByLabel('昵称').fill(nickname)
  const saved = await submit(page, 'PUT', '/api/user/profile', () =>
    page.getByRole('button', { name: '保存修改', exact: true }).click())
  assert.equal(record(saved.body.data).nickname, nickname)
  await page.reload()
  await page.getByRole('heading', { name: nickname, exact: true }).waitFor()
  assert.equal(await page.getByLabel('昵称').inputValue(), nickname)
  checks.push('Settings profile is saved by the real API and survives reload; role remains user')

  const pointsResponse = responseFor(page, 'GET', '/api/user/points')
  const logsResponse = responseFor(page, 'GET', '/api/user/points/logs')
  await page.goto(base + '/settings?tab=points')
  const points = record((await result(await pointsResponse)).body.data)
  const logs = records(record((await result(await logsResponse)).body.data).list)
  const balance = page.locator('.stat-card').filter({ hasText: '当前可用积分' }).locator('.stat-value')
  await page.locator('.points-log').first().waitFor()
  assert.equal(Number((await balance.innerText()).replaceAll(',', '')), points.balance)
  const traced = logs.find((item) => item.direction === 'out' && typeof item.request_id === 'string' && item.request_id)
  assert.ok(traced, 'Real chat settlement must appear in the points ledger')
  await page.locator('.points-request code').filter({ hasText: String(traced.request_id) }).waitFor()
  checks.push('Settings points balance and visible requestId match the real settlement ledger')
  for (const [label, direction] of [['积分支出', 'out'], ['积分入账', 'in']]) {
    const filtered = await submit(page, 'GET', '/api/user/points/logs', () =>
      page.getByRole('button', { name: label, exact: true }).click())
    const list = records(record(filtered.body.data).list)
    assert.ok(list.length > 0 && list.every((item) => item.direction === direction))
    await page.locator('.points-log').first().waitFor()
    assert.equal(new URL(page.url()).searchParams.get('direction'), direction)
  }
  checks.push('Settings incoming/outgoing filters issue real isolated ledger queries')
  await page.screenshot({ path: path.join(directory, 'settings-points-desktop.png'), fullPage: true })

  await page.goto(base + '/settings?tab=keys')
  await page.getByRole('button', { name: '新建 API Key', exact: true }).click()
  const create = page.getByRole('dialog', { name: '创建 API Key', exact: true })
  const name = 'QA Key ' + Date.now().toString(36)
  await create.getByLabel('名称').fill(name)
  await create.locator('input[type="datetime-local"]').fill(shanghaiDate(-3_600_000))
  let invalidWrites = 0
  const countWrite = (req: Request) => {
    if (req.method() === 'POST' && new URL(req.url()).pathname === '/api/user/apikeys') invalidWrites++
  }
  page.on('request', countWrite)
  await create.getByRole('button', { name: '创建 API Key', exact: true }).click()
  await create.getByText('请选择未来的有效期时间，或留空表示长期有效。', { exact: true }).waitFor()
  page.off('request', countWrite)
  assert.equal(invalidWrites, 0)
  checks.push('Settings rejects a past expiry before submitting a Key creation request')

  const expiry = shanghaiDate(300_000)
  await create.locator('input[type="datetime-local"]').fill(expiry)
  const creation = await submit(page, 'POST', '/api/user/apikeys', () =>
    create.getByRole('button', { name: '创建 API Key', exact: true }).click())
  assert.equal(creation.headers['cache-control'], 'no-store')
  const key = record(creation.body.data)
  const secret = key.secret_key, access = key.access_key
  assert.ok(typeof secret === 'string' && secret.length > 20, 'Expected a one-time Secret')
  assert.ok(typeof access === 'string' && typeof key.id === 'number')
  assert.equal(key.expire_time, expiry.replace('T', ' ') + ':00')
  const disclosure = page.getByRole('dialog', { name: '访问凭证已创建', exact: true })
  await disclosure.waitFor()
  assert.ok((await disclosure.locator('.key-secret-block code').nth(1).innerText()) === secret,
    'The one-time modal must show the just-created Secret')
  checks.push('Settings creates an expiring real Key with no-store and one-time Secret disclosure')
  await disclosure.locator('.ant-modal-close').click()
  await page.getByText('已经保存好密钥了吗？', { exact: true }).waitFor()
  await page.getByRole('button', { name: '继续查看', exact: true }).click()
  await disclosure.getByRole('button', { name: '我已安全保存', exact: true }).click()
  await disclosure.waitFor({ state: 'hidden' })
  await assertSecretAbsent(page, secret)
  checks.push('Settings guards accidental Secret dismissal and never persists the full Secret')

  const listingResponse = responseFor(page, 'GET', '/api/user/apikeys')
  await page.reload()
  const listed = records(record((await result(await listingResponse)).body.data).list)
  const item = listed.find((row) => row.id === key.id)
  assert.ok(item && typeof item.secret_mask === 'string' && item.secret_mask.includes('****'))
  assert.ok(listed.every((row) => !('secret_key' in row) && !('secret_hash' in row)))
  await page.getByRole('row').filter({ hasText: name }).waitFor()
  assert.equal(await page.getByRole('dialog', { name: '访问凭证已创建', exact: true }).count(), 0)
  await assertSecretAbsent(page, secret)
  checks.push('Settings reload returns only Key masks; full Secret cannot be retrieved again')

  const exchange = await request(page, 'POST', '/api/user/apikeys/exchange', {
    anonymous: true, data: { access_key: access, secret_key: secret },
  })
  assert.equal(exchange.headers['cache-control'], 'no-store')
  const token = record(exchange.body.data)
  assert.equal(token.user_id, profile.user_id)
  assert.equal(token.role, 'user')
  assert.ok(typeof token.expires_in === 'number' && token.expires_in > 0 && token.expires_in <= 300)
  assert.ok(typeof token.token === 'string' && typeof token.expire_at === 'string')
  assert.ok(Date.parse(token.expire_at) <= Date.parse(expiry + ':00+08:00'))
  const signed: unknown = JSON.parse(Buffer.from(token.token.split('.')[1], 'base64url').toString())
  const claims = record(signed)
  assert.ok(typeof claims.exp === 'number' && typeof claims.iat === 'number' && claims.exp - claims.iat <= 3600)
  assert.ok(claims.exp * 1000 <= Date.parse(expiry + ':00+08:00'))
  const bearer = { Authorization: 'Bearer ' + token.token }
  const exchangedProfile = record((await request(page, 'GET', '/api/user/profile', { headers: bearer })).body.data)
  assert.equal(exchangedProfile.user_id, profile.user_id)
  checks.push('Real anonymous Key exchange returns an expiry-bounded JWT accepted by Gateway')
  const wrong = await request(page, 'POST', '/api/user/apikeys/exchange', {
    anonymous: true, code: 1003, data: { access_key: access, secret_key: 'invalid-qa-credential' },
  })
  assert.equal(wrong.headers['cache-control'], 'no-store')
  const expired = await request(page, 'POST', '/api/user/apikeys', {
    data: { name: 'QA already expired', expire_time: shanghaiDate(-3_600_000).replace('T', ' ') + ':00' },
  })
  const old = record(expired.body.data)
  await request(page, 'POST', '/api/user/apikeys/exchange', {
    anonymous: true, code: 1003, data: { access_key: old.access_key, secret_key: old.secret_key },
  })
  checks.push('Wrong and already-expired real Key credentials are rejected without enumeration')

  const row = page.getByRole('row').filter({ hasText: name })
  await row.getByRole('button', { name: '禁用', exact: true }).click()
  const disabled = await submit(page, 'PUT', `/api/user/apikeys/${key.id}/disable`, () =>
    page.getByRole('button', { name: '确认禁用', exact: true }).click())
  assert.equal(record(disabled.body.data).status, 'disabled')
  await row.getByText('已禁用', { exact: true }).waitFor()
  assert.equal(await row.getByRole('button', { name: '禁用', exact: true }).isDisabled(), true)
  await request(page, 'POST', '/api/user/apikeys/exchange', {
    anonymous: true, code: 1003, data: { access_key: access, secret_key: secret },
  })
  // Disable blocks new exchanges, not already-issued unexpired JWTs.
  await request(page, 'GET', '/api/user/profile', { headers: bearer })
  await assertSecretAbsent(page, secret)
  checks.push('Settings disables the real Key and blocks new exchanges without claiming JWT revocation')
  await page.screenshot({ path: path.join(directory, 'settings-keys-desktop.png'), fullPage: true })

  await page.setViewportSize({ width: 390, height: 844 })
  await viewport(page, page.getByRole('button', { name: '新建 API Key', exact: true }))
  await page.screenshot({ path: path.join(directory, 'settings-keys-mobile.png'), fullPage: true })
  await page.goto(base + '/settings?tab=profile')
  await page.getByText('普通用户', { exact: true }).waitFor()
  await viewport(page, page.getByLabel('昵称'))
  await page.screenshot({ path: path.join(directory, 'settings-profile-mobile.png'), fullPage: true })
  checks.push('Settings Key and profile controls remain visible in the 390px mobile viewport')
}
