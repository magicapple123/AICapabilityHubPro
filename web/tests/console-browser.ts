/** Administrator CRUD uses only new QA rows and real Gateway/service responses. */
import assert from 'node:assert/strict'
import path from 'node:path'
import type { Page, Request } from 'playwright'
import { login, record, records, request, submit, viewport } from './member-browser-support.ts'

export async function runConsoleScenarios(
  page: Page, ordinary: Page, base: string, username: string, password: string,
  directory: string, checks: string[],
) {
  console.log('Browser phase: real administrator Console')
  await login(page, base, username, password)
  await page.goto(base + '/settings?tab=profile')
  await page.getByText('管理员', { exact: true }).waitFor()
  const admin = record((await request(page, 'GET', '/api/user/profile')).body.data)
  assert.equal(admin.role, 'admin')
  const user = record((await request(ordinary, 'GET', '/api/user/profile')).body.data)
  assert.notEqual(user.user_id, admin.user_id)
  checks.push('A separately registered administrator logs in through real signed authentication')

  const suffix = Date.now().toString(36)
  const categoryCode = 'qa-browser-category-' + suffix
  const forbidden = 'qa-browser-forbidden-' + suffix
  const forged = { 'X-User-Id': String(admin.user_id), 'X-User-Role': 'admin', role: 'admin' }
  await request(ordinary, 'GET', '/api/capability/manage', { code: 2007, headers: forged })
  await request(ordinary, 'POST', '/api/capability/categories', {
    code: 2007, headers: forged, data: { name: forbidden, code: forbidden },
  })
  await request(ordinary, 'GET', '/api/billing/stat/overview', { code: 1006, headers: forged })
  const normalCategories = records(record((await request(ordinary, 'GET', '/api/capability/categories')).body.data).list)
  assert.ok(normalCategories.every((item) => item.code !== forbidden))
  await ordinary.goto(base + '/console?tab=statistics')
  await ordinary.locator('.error-note').first().waitFor()
  assert.match(await ordinary.locator('.error-note').first().innerText(), /权限不足/)
  checks.push('Ordinary and forged-role requests cannot manage categories, read management lists or global statistics')

  await page.goto(base + '/console?tab=categories')
  await page.getByRole('button', { name: '新增分类', exact: true }).click()
  const addCategory = page.getByRole('dialog', { name: '新增分类', exact: true })
  const categoryName = 'QA分类-' + suffix
  await addCategory.getByLabel('分类名称').fill(categoryName)
  await addCategory.getByLabel('分类编码').fill(categoryCode)
  await addCategory.getByLabel('排序值').fill('17')
  const categoryResult = await submit(page, 'POST', '/api/capability/categories', () =>
    addCategory.getByRole('button', { name: '保存分类', exact: true }).click())
  const category = record(categoryResult.body.data)
  assert.ok(typeof category.id === 'number')
  assert.equal(category.code, categoryCode)
  await page.getByRole('row').filter({ hasText: categoryCode }).waitFor()
  checks.push('Console creates a real QA category and renders the persisted result')

  const updatedCategoryName = categoryName + '-已编辑'
  await page.getByRole('button', { name: '编辑分类' + categoryName, exact: true }).click()
  const editCategory = page.getByRole('dialog', { name: '编辑分类', exact: true })
  await editCategory.getByLabel('分类名称').fill(updatedCategoryName)
  await editCategory.getByLabel('排序值').fill('19')
  await editCategory.getByRole('combobox', { name: /^状态/ }).selectOption('disabled')
  const categoryEdit = await submit(page, 'PUT', `/api/capability/categories/${category.id}`, () =>
    editCategory.getByRole('button', { name: '保存分类', exact: true }).click())
  assert.equal(record(categoryEdit.body.data).status, 'disabled')
  await page.getByRole('row').filter({ hasText: categoryCode }).getByText('已禁用', { exact: true }).waitFor()
  await page.getByRole('button', { name: '编辑分类' + updatedCategoryName, exact: true }).click()
  await editCategory.getByRole('combobox', { name: /^状态/ }).selectOption('enabled')
  const enabled = await submit(page, 'PUT', `/api/capability/categories/${category.id}`, () =>
    editCategory.getByRole('button', { name: '保存分类', exact: true }).click())
  assert.equal(record(enabled.body.data).sort, 19)
  await page.getByRole('row').filter({ hasText: categoryCode }).getByText('已启用', { exact: true }).waitFor()
  checks.push('Console persists category edits and disable/re-enable transitions')

  await page.goto(base + '/console?tab=capabilities')
  await page.getByRole('button', { name: '登记新能力', exact: true }).click()
  const editor = page.getByRole('dialog', { name: '登记新能力', exact: true })
  const code = 'qa-browser-capability-' + suffix
  const capabilityName = 'QA能力-' + suffix
  await editor.getByLabel('能力名称').fill(capabilityName)
  await editor.getByLabel('能力编码').fill(code)
  await editor.getByLabel('所属分类').selectOption(String(category.id))
  await editor.getByLabel('每次调用积分').fill('6')
  await editor.getByLabel('服务名').fill('ai-chat-service')
  await editor.getByLabel('调用路径').fill('/completions')
  const schemaInput = editor.getByLabel('输入 Schema')
  await schemaInput.fill(JSON.stringify({ type: 'object', $ref: 'https://invalid.example/schema' }))
  let invalidWrites = 0
  const countWrite = (req: Request) => {
    if (req.method() === 'POST' && new URL(req.url()).pathname === '/api/capability') invalidWrites++
  }
  page.on('request', countWrite)
  await editor.getByRole('button', { name: '保存能力', exact: true }).click()
  await editor.locator('.error-note').getByText('Schema 不能使用', { exact: false }).waitFor()
  page.off('request', countWrite)
  assert.equal(invalidWrites, 0)
  checks.push('Console blocks forbidden Schema references before submitting to the service')
  const schema = { type: 'object', properties: { text: { type: 'string', minLength: 1, maxLength: 300 } },
    required: ['text'], additionalProperties: false }
  await schemaInput.fill(JSON.stringify(schema))
  await editor.getByLabel('初始状态').selectOption('draft')
  const creation = await submit(page, 'POST', '/api/capability', () =>
    editor.getByRole('button', { name: '保存能力', exact: true }).click())
  const capability = record(creation.body.data)
  assert.ok(typeof capability.id === 'number')
  assert.equal(capability.status, 'draft')
  assert.deepEqual(capability.param_schema, schema)
  const row = page.getByRole('row').filter({ hasText: code })
  await row.getByText('草稿', { exact: true }).waitFor()
  await request(ordinary, 'GET', `/api/capability/market/${capability.id}`, { anonymous: true, code: 2002 })
  checks.push('Console creates a draft with persisted Schema/price; public detail does not reveal it')

  await page.getByRole('button', { name: '编辑能力' + capabilityName, exact: true }).click()
  const edit = page.getByRole('dialog', { name: '编辑能力', exact: true })
  const updatedName = capabilityName + '-已编辑'
  await edit.getByLabel('能力名称').fill(updatedName)
  await edit.getByLabel('每次调用积分').fill('7')
  await edit.getByLabel('能力描述').fill('QA isolated browser acceptance')
  const edited = await submit(page, 'PUT', `/api/capability/${capability.id}`, () =>
    edit.getByRole('button', { name: '保存能力', exact: true }).click())
  assert.equal(record(edited.body.data).price_per_call, 7)
  assert.deepEqual(record(edited.body.data).param_schema, schema)
  await row.getByText('7 积分', { exact: true }).waitFor()
  await page.reload()
  await page.getByRole('button', { name: '编辑能力' + updatedName, exact: true }).click()
  assert.equal(await edit.getByLabel('每次调用积分').inputValue(), '7')
  assert.deepEqual(JSON.parse(await edit.getByLabel('输入 Schema').inputValue()), schema)
  await edit.getByRole('button', { name: '取消', exact: true }).click()
  checks.push('Console capability edits and Schema/price survive a real reload')

  await row.getByRole('button', { name: '上架', exact: true }).click()
  const published = await submit(page, 'PUT', `/api/capability/${capability.id}/status`, () =>
    page.getByRole('button', { name: '确认上架', exact: true }).click())
  assert.equal(record(published.body.data).status, 'online')
  await row.getByText('已上架', { exact: true }).waitFor()
  await page.screenshot({ path: path.join(directory, 'console-capabilities-desktop.png'), fullPage: true })
  await ordinary.goto(base + '/capabilities?q=' + code)
  const card = ordinary.locator('.capability-card').filter({ hasText: code })
  await card.waitFor()
  await card.getByText('暂无执行器', { exact: true }).waitFor()
  assert.equal(await card.locator('.capability-launch').isDisabled(), true)
  await card.getByRole('button', { name: '查看' + updatedName + '详情', exact: true }).click()
  const detailDialog = ordinary.getByRole('dialog', { name: updatedName, exact: true })
  await detailDialog.getByText('必填', { exact: true }).waitFor()
  assert.match(await detailDialog.locator('.schema-constraints').innerText(), /300/)
  const publicDetail = record((await request(ordinary, 'GET', `/api/capability/market/${capability.id}`,
    { anonymous: true })).body.data)
  assert.deepEqual(publicDetail.param_schema, schema)
  assert.ok(!('service_name' in publicDetail) && !('path' in publicDetail))
  checks.push('Publishing updates the real public market and parameter preview without enabling an unknown executor')

  await row.getByRole('button', { name: '下架', exact: true }).click()
  const offline = await submit(page, 'PUT', `/api/capability/${capability.id}/status`, () =>
    page.getByRole('button', { name: '确认下架', exact: true }).click())
  assert.equal(record(offline.body.data).status, 'offline')
  await row.getByText('已下架', { exact: true }).waitFor()
  await ordinary.goto(base + '/capabilities?q=' + code)
  await ordinary.getByText('没有找到符合条件的能力。', { exact: false }).waitFor()
  assert.equal(await ordinary.locator('.capability-card').filter({ hasText: code }).count(), 0)
  await request(ordinary, 'GET', `/api/capability/market/${capability.id}`, { anonymous: true, code: 2002 })
  checks.push('Unpublishing removes the capability from the real market and conceals its detail')
  await page.getByRole('button', { name: '删除能力' + updatedName, exact: true }).click()
  const removed = await submit(page, 'DELETE', `/api/capability/${capability.id}`, () =>
    page.getByRole('button', { name: '确认删除', exact: true }).click())
  assert.equal(record(removed.body.data).is_deleted, 1)
  await row.waitFor({ state: 'detached' })
  await page.goto(base + '/console?tab=categories')
  await page.getByRole('button', { name: '删除分类' + updatedCategoryName, exact: true }).click()
  const categoryRemoved = await submit(page, 'DELETE', `/api/capability/categories/${category.id}`, () =>
    page.getByRole('button', { name: '确认删除', exact: true }).click())
  assert.equal(record(categoryRemoved.body.data).is_deleted, 1)
  await page.getByRole('row').filter({ hasText: categoryCode }).waitFor({ state: 'detached' })
  checks.push('Console soft-deletes only the new QA capability and now-empty QA category')

  const statistics = await submit(page, 'GET', '/api/billing/stat/overview', () =>
    page.goto(base + '/console?tab=statistics'))
  const totals = record(record(statistics.body.data).summary)
  assert.ok(typeof totals.call_count === 'number' && totals.call_count > 0)
  assert.ok(typeof totals.user_count === 'number' && totals.user_count >= 1)
  await page.getByRole('heading', { name: '平台调用趋势', exact: true }).waitFor()
  const calls = await page.locator('.stat-card').filter({ hasText: '平台调用' }).locator('.stat-value').innerText()
  assert.equal(Number(calls.replaceAll(',', '')), totals.call_count)
  await page.screenshot({ path: path.join(directory, 'console-statistics-desktop.png'), fullPage: true })
  checks.push('Administrator global statistics render the real accumulated billing totals')
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto(base + '/console?tab=categories')
  await page.locator('.data-table tbody tr').first().waitFor()
  await viewport(page, page.getByRole('button', { name: '新增分类', exact: true }))
  await page.screenshot({ path: path.join(directory, 'console-categories-mobile.png'), fullPage: true })
  checks.push('Administrator category controls remain visible in the 390px mobile viewport')
}
