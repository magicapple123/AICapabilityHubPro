import { randomBytes, randomUUID } from 'node:crypto'
import { spawnSync } from 'node:child_process'
import { createRequire } from 'node:module'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const require = createRequire(resolve(root, 'web/package.json'))
const { chromium } = require('playwright')
const gateway = process.env.P4_GATEWAY_URL || 'http://127.0.0.1:8080'
const web = process.env.P4_WEB_URL || 'http://127.0.0.1:28088'
const baseline = process.env.P4_BASELINE_ONLY === '1'
const suffix = randomBytes(4).toString('hex')
const prefix = `P4-${baseline ? 'before' : 'after'}-${suffix}`
const output = resolve(root, 'artifacts/verify-2026-11-03')
const assert = (value, message) => { if (!value) throw new Error(message) }
let stage = 'bootstrap', browser
try {
  const username = `qa-p4-admin-${suffix}`
  const password = randomBytes(24).toString('hex')
  const bootstrap = spawnSync('C:/Program Files/Git/bin/bash.exe', ['scripts/bootstrap_stack.sh'], {
    cwd: root, encoding: 'utf8',
    env: { ...process.env, COMPOSE_PROJECT_NAME: 'aihub-pro-verify',
      COMPOSE_OVERRIDE_FILE: 'deploy/docker-compose.verify.yml',
      BOOTSTRAP_ADMIN_USERNAME: username, BOOTSTRAP_ADMIN_PASSWORD: password },
  })
  assert(bootstrap.status === 0, 'QA admin bootstrap failed')
  const api = async (method, path, body, token, requestId) => {
    const response = await fetch(`${gateway}${path}`, {
      method, headers: { 'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(requestId ? { 'X-Request-Id': requestId } : {}) },
      ...(body ? { body: JSON.stringify(body) } : {}),
    })
    const payload = await response.json()
    assert(response.ok && payload.code === 0, `HTTP ${response.status}, code=${payload.code}, path=${path}`)
    return payload.data
  }
  stage = 'seed-audit'
  const admin = await api('POST', '/api/user/login', { username, password })
  const categories = await api('GET', '/api/capability/categories', null, admin.token)
  assert(categories.list?.length > 0, 'No category in isolated acceptance database')
  const requestId = randomUUID()
  const properties = Object.fromEntries(Array.from({ length: 12 }, (_, index) => [
    `verification_field_${index}`, { type: 'string', description: 'P4 synthetic long schema value '.repeat(5) },
  ]))
  const capability = await api('POST', '/api/capability', {
    name: `P4 layout verification ${suffix}`, code: `p4-live-${suffix}`,
    category_id: categories.list[0].id, service_name: 'ai-chat-service',
    path: '/api/chat/completions', status: 'draft', price_per_call: 5,
    param_schema: { type: 'object', properties, additionalProperties: false },
    description: 'P4 synthetic long audit description '.repeat(12),
  }, admin.token, requestId)
  stage = 'browser-login'
  browser = await chromium.launch({ headless: true })
  const context = await browser.newContext({ permissions: ['clipboard-read', 'clipboard-write'] })
  const page = await context.newPage()
  await page.setViewportSize({ width: 1440, height: 1100 })
  await page.goto(`${web}/login`, { waitUntil: 'domcontentloaded' })
  await page.getByRole('textbox', { name: '账号', exact: true }).fill(username)
  await page.locator('input[type=password]').fill(password)
  await page.getByRole('button', { name: '登录工作空间' }).click()
  await page.waitForURL((url) => url.pathname === '/', { timeout: 20000 })
  stage = 'audit-viewports'
  await page.goto(`${web}/console?tab=audit`, { waitUntil: 'domcontentloaded' })
  const table = page.locator('.panel .data-table').first()
  await table.locator('tbody tr').first().waitFor({ state: 'visible', timeout: 20000 })
  const measurements = []
  for (const width of [1440, 1280, 1024, 375]) {
    await page.setViewportSize({ width, height: 1100 })
    await page.waitForTimeout(150)
    const result = await table.evaluate((element) => {
      const wrap = element.parentElement
      return { clientWidth: wrap.clientWidth, scrollWidth: wrap.scrollWidth,
        documentClientWidth: document.documentElement.clientWidth,
        documentScrollWidth: document.documentElement.scrollWidth,
        rowDisplay: getComputedStyle(element.querySelector('tbody tr')).display }
    })
    const path = resolve(output, `${prefix}-${width}.png`)
    await page.screenshot({ path, fullPage: false })
    measurements.push({ viewport: width, ...result, screenshot: path })
    if (!baseline) {
      assert(result.scrollWidth === result.clientWidth, `Audit horizontal overflow at ${width}: ${result.scrollWidth - result.clientWidth}`)
      assert(result.documentScrollWidth === result.documentClientWidth, `Page horizontal overflow at ${width}`)
      if (width === 375) assert(result.rowDisplay === 'block', 'Mobile audit cards missing')
    }
  }
  if (!baseline) {
    stage = 'copy-and-expand'
    await page.setViewportSize({ width: 1024, height: 1100 })
    const row = table.locator('tbody tr').first()
    const fullId = await row.locator('.audit-request [title]').getAttribute('title')
    assert(fullId?.length === 36, 'Audit requestId is not a full UUID')
    await row.getByRole('button', { name: '复制完整 requestId' }).click()
    const copied = await page.evaluate(() => navigator.clipboard.readText())
    assert(copied === fullId, 'Clipboard did not receive the complete requestId')
    await row.locator('summary').click()
    const after = await row.locator('.audit-snapshots pre').last().textContent()
    assert(after.includes('verification_field_11'), 'Expanded snapshot is incomplete')
    const expanded = resolve(output, `${prefix}-expanded.png`)
    await page.screenshot({ path: expanded, fullPage: false })
    console.log(`P4_COPY uuid_length=${copied.length} equal=true request_id=${fullId}; expanded_schema_fields=12 screenshot=${expanded}`)
  }
  console.log(`P4_AUDIT capability_id=${capability.id} request_id=${requestId} mode=${baseline ? 'before' : 'after'}`)
  for (const result of measurements) console.log(JSON.stringify(result))
  console.log(`P4_RESULT=${baseline ? 'BASELINE' : 'PASS'}`)
} catch (error) {
  console.error(`P4_FAILED stage=${stage} reason=${error.message}`)
  process.exitCode = 1
} finally {
  if (browser) await browser.close()
}
