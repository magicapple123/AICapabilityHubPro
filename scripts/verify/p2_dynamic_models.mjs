import { randomBytes } from 'node:crypto'
import { spawnSync } from 'node:child_process'
import { createRequire } from 'node:module'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const require = createRequire(resolve(root, 'web', 'package.json'))
const { chromium } = require('playwright')
const gateway = process.env.P2_GATEWAY_URL || 'http://127.0.0.1:8080'
const web = process.env.P2_WEB_URL || 'http://127.0.0.1:28088'
const outputDir = resolve(root, 'artifacts', 'verify-2026-11-03')
const screenshotSuffix = randomBytes(4).toString('hex')
const screenshot = (name) => resolve(outputDir, name.replace(/^P2-/, `P2-${screenshotSuffix}-`))

function assert(condition, message) {
  if (!condition) throw new Error(message)
}

async function postJson(path, body, token) {
  const response = await fetch(`${gateway}${path}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
  })
  const payload = await response.json().catch(() => ({}))
  assert(response.ok && payload.code === 0, `request failed: ${path} HTTP ${response.status} code=${payload.code}`)
  return payload.data
}

async function getModels(secretKey) {
  const response = await fetch(`${gateway}/v1/models`, {
    headers: { Authorization: `Bearer ${secretKey}` },
  })
  const payload = await response.json().catch(() => ({}))
  return { status: response.status, payload }
}

async function measureChatCompletions(secretKey, modelAlias, requestCount = 100, concurrency = 10) {
  let next = 0
  let succeeded = 0
  let failed = 0
  let totalCost = 0
  let firstRequestId = ''
  const latencies = []
  const started = performance.now()
  const worker = async () => {
    while (true) {
      const index = next++
      if (index >= requestCount) return
      const begin = performance.now()
      let result
      try {
        const response = await fetch('http://127.0.0.1:8090/v1/chat/completions', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${secretKey}` },
          body: JSON.stringify({
            model: modelAlias,
            messages: [{ role: 'user', content: `P2 throughput verification ${index}` }],
          }),
        })
        result = { status: response.status, payload: await response.json().catch(() => ({})) }
      } catch {
        result = { status: 0, payload: {} }
      }
      latencies.push(performance.now() - begin)
      if (result.status === 200 && Number(result.payload.platform_cost) > 0) {
        succeeded++
        totalCost += Number(result.payload.platform_cost)
        if (!firstRequestId) firstRequestId = String(result.payload.platform_request_id || '')
      } else failed++
    }
  }
  await Promise.all(Array.from({ length: concurrency }, worker))
  const elapsedSeconds = (performance.now() - started) / 1000
  latencies.sort((a, b) => a - b)
  return {
    requestCount,
    concurrency,
    succeeded,
    failed,
    totalCost,
    firstRequestId,
    qps: succeeded / elapsedSeconds,
    p50Ms: latencies[Math.floor(latencies.length * 0.5)] ?? 0,
  }
}

function cacheMetric(metrics, result) {
  const match = metrics.match(new RegExp(`catalog_cache_events_total\\{[^}]*result="models-${result}"[^}]*\\}\\s+([0-9.]+)`))
  return match ? Number(match[1]) : null
}

let stage = 'bootstrap'
let browser
let debugPage
try {
  const suffix = randomBytes(4).toString('hex')
  const adminUsername = `qa-p2-admin-${suffix}`
  const adminPassword = randomBytes(24).toString('hex')
  const bootstrap = spawnSync(
    'C:\\Program Files\\Git\\bin\\bash.exe',
    ['scripts/bootstrap_stack.sh'],
    {
      cwd: root,
      encoding: 'utf8',
      env: {
        ...process.env,
        COMPOSE_PROJECT_NAME: 'aihub-pro-verify',
        COMPOSE_OVERRIDE_FILE: 'deploy/docker-compose.verify.yml',
        BOOTSTRAP_ADMIN_USERNAME: adminUsername,
        BOOTSTRAP_ADMIN_PASSWORD: adminPassword,
      },
    },
  )
  assert(bootstrap.status === 0, 'isolated QA admin bootstrap failed')

  stage = 'admin-auth'
  const admin = await postJson('/api/user/login', {
    username: adminUsername,
    password: adminPassword,
  })
  const adminToken = admin.token
  assert(typeof adminToken === 'string' && adminToken.length > 0, 'admin login returned no token')
  await postJson('/api/user/admin/users/1/points', {
    amount: 5000,
    reason: 'P2 isolated throughput acceptance',
  }, adminToken)

  stage = 'capability-ui'
  browser = await chromium.launch({ headless: true })
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
  debugPage = page
  stage = 'ui-login'
  await page.goto(`${web}/login`, { waitUntil: 'domcontentloaded' })
  await page.getByRole('textbox', { name: '账号', exact: true }).fill(adminUsername)
  await page.locator('input[type="password"]').fill(adminPassword)
  await page.getByRole('button', { name: '登录工作空间' }).click()
  await page.waitForURL((url) => url.pathname === '/', { timeout: 20000 })
  stage = 'ui-console-navigation'
  await page.goto(`${web}/console?tab=capabilities`, { waitUntil: 'domcontentloaded' })
  await page.getByRole('button', { name: '登记新能力', exact: true }).waitFor({ state: 'visible' })
  await page.getByRole('button', { name: '登记新能力', exact: true }).click()

  stage = 'ui-open-editor'
  const dialog = page.getByRole('dialog', { name: '登记新能力', exact: true })
  const capabilityName = `QA P2 Model ${suffix}`
  const capabilityCode = `p2-live-${suffix}`
  const firstAlias = `qa-model-${suffix}`
  const finalAlias = `${firstAlias}-v2`
  const schema = {
    type: 'object',
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
    },
    required: ['messages'],
    additionalProperties: false,
  }
  stage = 'ui-fill-editor'
  // P8/P9 改版后的表单：字段都有稳定 id，服务名/调用路径已预填（折叠在高级字段里）。
  await dialog.locator('#cap-name').fill(capabilityName)
  await dialog.locator('#cap-code').fill(capabilityCode)
  await dialog.locator('#cap-category').selectOption({ index: 1 })
  await dialog.locator('#cap-alias').fill(firstAlias)
  await dialog.locator('#cap-executor').selectOption('chat')
  await dialog.locator('#cap-price-call').fill('5')
  await dialog.locator('textarea.cap-schema-input').fill(JSON.stringify(schema, null, 2))
  await dialog.locator('#cap-status').selectOption('online')
  await page.screenshot({ path: screenshot('P2-capability-editor.png'), fullPage: false })
  stage = 'ui-save-editor'
  await dialog.getByRole('button', { name: '保存能力' }).click()
  await dialog.waitFor({ state: 'detached', timeout: 20000 })
  const managedResponse = await fetch(
    `${gateway}/api/capability/manage?keyword=${encodeURIComponent(capabilityCode)}&page=1&page_size=10`,
    { headers: { Authorization: `Bearer ${adminToken}` } },
  )
  const managedPayload = await managedResponse.json().catch(() => ({}))
  const capability = managedPayload.data?.list?.find((item) => item.code === capabilityCode)
  assert(managedResponse.ok && capability, 'created capability is missing from the admin directory')

  stage = 'ui-models-tab'
  await page.getByRole('button', { name: '模型服务', exact: true }).click()
  stage = 'ui-models-wait'
  await page.getByRole('heading', { name: '模型服务', exact: false }).waitFor({ state: 'visible', timeout: 20000 })
  const capabilityRow = page.locator('.panel').first().locator('tbody tr').filter({ hasText: capabilityName })
  await capabilityRow.waitFor({ state: 'visible', timeout: 20000 })
  stage = 'ui-alias-input'
  const aliasInput = capabilityRow.locator('input[aria-label^="对外模型名"]')
  await aliasInput.waitFor({ state: 'visible', timeout: 20000 })
  stage = 'ui-alias-value'
  await page.waitForFunction(
    ({ label, value }) => document.querySelector(`input[aria-label="${label}"]`)?.value === value,
    { label: `对外模型名 ${capabilityName}`, value: firstAlias },
  )
  stage = 'ui-save-alias'
  await aliasInput.fill(finalAlias)
  await capabilityRow.getByRole('button', { name: `保存对外模型名 ${capabilityName}` }).click()
  await page.waitForFunction(
    ({ label, value }) => document.querySelector(`input[aria-label="${label}"]`)?.value === value,
    { label: `对外模型名 ${capabilityName}`, value: finalAlias },
    { timeout: 15000 },
  )
  await page.locator('.panel').first().screenshot({ path: screenshot('P2-model-service.png') })

  stage = 'api-key'
  const demo = await postJson('/api/user/login', { username: 'demo', password: 'demo123456' })
  const keyData = await postJson('/api/user/apikeys', { name: `p2-${suffix}` }, demo.token)
  const secretKey = keyData.secret_key
  assert(typeof secretKey === 'string' && secretKey.startsWith('sk_'), 'API Key creation failed')

  stage = 'models-list'
  const modelsStarted = performance.now()
  let modelResult
  do {
    modelResult = await getModels(secretKey)
    if (modelResult.status === 200 && modelResult.payload.data?.some((item) => item.id === finalAlias)) break
    await new Promise((resolveWait) => setTimeout(resolveWait, 150))
  } while (performance.now() - modelsStarted < 6000)
  const modelsVisibleMs = Math.round(performance.now() - modelsStarted)
  assert(modelResult?.status === 200, `models endpoint returned HTTP ${modelResult?.status}`)
  assert(modelResult.payload.data.some((item) => item.id === finalAlias), 'dynamic alias not visible within 6 seconds')

  const modelsPage = await browser.newPage({
    viewport: { width: 1120, height: 760 },
    extraHTTPHeaders: { Authorization: `Bearer ${secretKey}` },
  })
  const modelsResponse = await modelsPage.goto(`${gateway}/v1/models`, { waitUntil: 'load' })
  assert(modelsResponse?.status() === 200, 'models screenshot request failed')
  await modelsPage.screenshot({ path: screenshot('P2-models.png'), fullPage: true })
  await modelsPage.close()

  stage = 'compat-completion'
  const callResponse = await fetch(`${gateway}/v1/chat/completions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${secretKey}` },
    body: JSON.stringify({
      model: finalAlias,
      messages: [{ role: 'user', content: `P2 alias verification ${suffix}` }],
    }),
  })
  const callData = await callResponse.json().catch(() => ({}))
  assert(callResponse.status === 200, `compat completion returned HTTP ${callResponse.status} code=${callData.error?.code}`)
  assert(Number(callData.platform_cost) > 0, 'compat completion did not record a positive platform cost')

  const receipt = {
    http_status: callResponse.status,
    model_alias: finalAlias,
    platform_cost: callData.platform_cost,
    platform_request_id: callData.platform_request_id,
    usage: callData.usage,
  }
  const receiptPage = await browser.newPage({ viewport: { width: 900, height: 650 } })
  await receiptPage.setContent(`<main style="font:16px system-ui;padding:32px"><h1>P2 OpenAI 兼容调用回执</h1><pre>${JSON.stringify(receipt, null, 2)}</pre></main>`)
  await receiptPage.screenshot({ path: screenshot('P2-completion-receipt.png'), fullPage: true })
  await receiptPage.close()

  stage = 'throughput'
  const throughput = await measureChatCompletions(secretKey, finalAlias)
  const metricsResponse = await fetch('http://127.0.0.1:8090/metrics')
  const metricsText = metricsResponse.ok ? await metricsResponse.text() : ''
  const cacheHits = cacheMetric(metricsText, 'hit')
  const cacheMisses = cacheMetric(metricsText, 'miss')
  const perfPass = throughput.failed === 0 && throughput.qps >= 30.7

  console.log(`P2_ALIAS capability_id=${capability.id} alias=${finalAlias} visible_ms=${modelsVisibleMs} models_http=${modelResult.status} completion_http=${callResponse.status} platform_cost=${callData.platform_cost} request_id=${callData.platform_request_id}`)
  const cacheFetches = cacheMetric(metricsText, 'fetch')
  console.log(`P2_COMPAT_LOAD c=${throughput.concurrency} n=${throughput.requestCount} success=${throughput.succeeded} failed=${throughput.failed} cost_total=${throughput.totalCost} qps=${throughput.qps.toFixed(1)} p50_ms=${throughput.p50Ms.toFixed(1)} threshold=30.7 result=${perfPass ? 'PASS' : 'FAIL'} cache_hits=${cacheHits} cache_misses=${cacheMisses} cache_fetches=${cacheFetches} request_id=${throughput.firstRequestId}`)
  console.log(`P2_SCREENSHOTS ${['capability-editor', 'model-service', 'models', 'completion-receipt'].map((name) => screenshot(`P2-${name}.png`).replace(`${root}\\`, '')).join(' ')}`)
  assert(perfPass, 'concurrency-10 OpenAI compatibility QPS is below the 30.7 baseline')
  await browser.close()
} catch (error) {
  if (debugPage && !debugPage.isClosed()) {
    await debugPage.screenshot({ path: screenshot('P2-debug.png'), fullPage: true }).catch(() => {})
  }
  if (browser) await browser.close().catch(() => {})
  console.error(`P2_LIVE_FAIL stage=${stage} error_type=${error?.name ?? 'Error'} debug_screenshot=${screenshot('P2-debug.png').replace(`${root}\\`, '')}`)
  process.exitCode = 1
}
