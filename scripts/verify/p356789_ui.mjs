/**
 * P3 / P5 / P7 / P8 / P9 / P10 的实机取证：
 * - 断言只打在**接口事实**上（别名清单、聚合、预算、市场 executor），避免 brittle UI 断言；
 * - 截图覆盖：用户与用量页、按 Key 分布抽屉、调分弹窗（两态）、使用方法抽屉、
 *   能力登记表单（1440 / 375）、市场卡片、调用记录来源列。
 *
 * 用独立管理员账号登录 28088（不碰 opsdemo 的数据）。
 */
import { createRequire } from 'node:module'
import { resolve } from 'node:path'
import {
  admin, assert, evidence, gateway, ok, outputDir, root,
} from './runtime_support.mjs'

const require = createRequire(resolve(root, 'web/package.json'))
const { chromium } = require('playwright')
const BASE = 'http://127.0.0.1:28088'
const shots = []
const failures = []

async function shot(page, name) {
  const path = resolve(outputDir, `P356789-${name}.png`)
  await page.screenshot({ path, fullPage: false })
  shots.push(path)
  return path
}

async function step(name, fn) {
  try {
    await fn()
    return { name, ok: true }
  } catch (cause) {
    failures.push({ name, error: String(cause && cause.message ? cause.message : cause) })
    return { name, ok: false }
  }
}

const operator = await admin('P356789')
const profile = await ok('/api/user/profile', { token: operator.token })
const userId = profile.id ?? profile.user_id
assert(typeof userId === 'number' && userId > 0, '无法解析管理员用户 ID')

// ---------------- P3：对外模型名清单（设置页抽屉的数据源）
const models = await ok('/api/capability/models', { token: operator.token })
assert(Array.isArray(models.list), '模型清单出参缺 list')
const aliasSample = models.list.slice(0, 5).map((row) => row.alias)

// ---------------- P5：全量用户聚合
// 先产生一次真实调用，聚合表（t_usage_daily）里才会有这个用户。
const warmCall = await ok('/api/chat/completions', {
  method: 'POST',
  token: operator.token,
  body: { capability_id: 1, input: { messages: [{ role: 'user', content: 'p5 aggregate warm' }] } },
})
assert(warmCall.cost === 5, '预热调用应扣 5 分')
const aggregates = await ok('/api/billing/admin/users/usage', { token: operator.token })
assert(Array.isArray(aggregates.list), '用户聚合出参缺 list')
const self = aggregates.list.find((row) => row.user_id === userId)
assert(self && typeof self.total_cost === 'number', '聚合里找不到当前管理员')

// ---------------- P10：日预算 5 → 立即生效 → 0（不限）
await ok(`/api/user/admin/users/${userId}/budget`, {
  method: 'PUT', token: operator.token, body: { daily_points_limit: 5 },
})
const resetBudget = await ok(`/api/user/admin/users/${userId}/budget`, {
  method: 'PUT', token: operator.token, body: { daily_points_limit: 0 },
})
assert(resetBudget.daily_points_limit === 0, '预算无法恢复到不限')
const budgetAudit = await ok(
  `/api/user/admin/audit?resource_type=user&resource_id=${userId}&action=budget`,
  { token: operator.token },
)
assert(budgetAudit.list.length >= 2, '预算变更审计不足 2 条')

// ---------------- P8：市场出参带 executor
const market = await ok('/api/capability/market?page_size=100')
const withExecutor = market.list.filter((row) => row.executor === 'chat')
assert(withExecutor.length >= 1, '市场列表没有任何 executor=chat 的能力')

// ---------------- 浏览器取证
const browser = await chromium.launch({ headless: true })
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
  await page.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded' })
  await page.fill('input[name="username"]', operator.username)
  await page.fill('input[name="password"]', operator.password)
  await page.click('button[type="submit"]')
  await page.waitForURL(`${BASE}/`, { timeout: 20000 })

  // P5：旧 tab 重定向 + 新页签
  await step('P5-legacy-tab-redirect', async () => {
    await page.goto(`${BASE}/console?tab=statistics`, { waitUntil: 'domcontentloaded' })
    await page.waitForURL(/tab=users-usage/, { timeout: 15000 })
    await page.waitForSelector('text=近 30 天消耗', { timeout: 20000 })
    await shot(page, '01-users-usage')
  })

  // P5：按 ID 搜索
  await step('P5-search-by-id', async () => {
    const search = page.locator('input[placeholder*="搜索"], input[placeholder*="用户"]').first()
    await search.fill(String(userId))
    await page.waitForTimeout(900)
    await page.waitForSelector(`text=#${userId}`, { timeout: 15000 })
    await shot(page, '02-search-by-id')
  })

  // P6-FE / P10：抽屉里的按 Key 分布与日预算
  await step('P6-P10-drawer', async () => {
    await page.getByRole('button', { name: '详情' }).first().click()
    await page.waitForSelector('text=按 Key', { timeout: 20000 })
    await page.waitForSelector('text=日预算', { timeout: 20000 })
    await shot(page, '03-user-drawer')
    await page.keyboard.press('Escape')
  })

  // P7：调分弹窗（余额不足态 + 可提交态）
  await step('P7-points-modal', async () => {
    // 先回到列表页，确保抽屉已关闭（否则遮罩会挡住调分按钮）。
    await page.goto(`${BASE}/console?tab=users-usage`, { waitUntil: 'domcontentloaded' })
    await page.waitForSelector('text=近 30 天消耗', { timeout: 20000 })
    await page.getByRole('button', { name: '调分' }).first().click()
    const amount = page.locator('.points-form .ant-input-number-input').first()
    await amount.waitFor({ state: 'visible', timeout: 20000 })
    await amount.fill('-999999')
    await page.waitForTimeout(500)
    const blocked = await page.locator('text=最多可扣').count()
    await shot(page, '04-points-modal-overflow')
    await amount.fill('50')
    const reason = page.locator('.points-form textarea')
    await reason.fill('活动奖励：P7 实机取证')
    await page.waitForTimeout(300)
    await shot(page, '05-points-modal-ready')
    assert(blocked >= 1, '扣减超过余额时没有出现「最多可扣」提示')
    await page.keyboard.press('Escape')
  })

  // P8/P9：能力登记表单（1440 / 375）
  await step('P8-P9-editor', async () => {
    await page.goto(`${BASE}/console?tab=capabilities`, { waitUntil: 'domcontentloaded' })
    await page.getByRole('button', { name: /登记新能力/ }).click()
    await page.waitForSelector('#cap-executor', { timeout: 20000 })
    const box = await page.locator('#cap-schema-template-label').boundingBox()
    assert(box && box.height < 30, '「Schema 模板」标签发生折行，height=' + (box && box.height))
    await shot(page, '06-capability-editor-1440')
    await page.setViewportSize({ width: 375, height: 900 })
    await page.waitForTimeout(400)
    await shot(page, '07-capability-editor-375')
    await page.setViewportSize({ width: 1440, height: 1000 })
    await page.keyboard.press('Escape')
  })

  // P3：使用方法抽屉（设置页默认在「个人资料」，API Key 是 ?tab=keys）
  await step('P3-usage-drawer', async () => {
    await page.goto(`${BASE}/settings?tab=keys`, { waitUntil: 'domcontentloaded' })
    await page.getByRole('button', { name: /使用方法/ }).first().click()
    await page.waitForSelector('text=两套凭证不可互换', { timeout: 20000 })
    await shot(page, '08-usage-openai')
    await page.getByRole('tab', { name: '平台 API' }).click()
    await page.waitForTimeout(400)
    await shot(page, '09-usage-platform')
    await page.getByRole('tab', { name: '客户端配置' }).click()
    await page.waitForTimeout(400)
    await shot(page, '10-usage-client')
    await page.keyboard.press('Escape')
  })

  // P8：市场卡片可调试、无「暂无执行器」
  await step('P8-market-card', async () => {
    await page.goto(`${BASE}/capabilities`, { waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(1200)
    // 市场卡片上"开始调试"是一个链接（不是按钮），禁用态才是 button。
    const launchLinks = await page.locator('a.capability-launch').count()
    const empty = await page.locator('text=暂无执行器').count()
    await shot(page, '11-market-card')
    assert(launchLinks >= 1, '市场里没有任何可调试的能力')
    assert(empty === 0, '市场仍在显示「暂无执行器」')
  })

  // P6-FE：调用记录的来源列
  await step('P6-records-source-column', async () => {
    await page.goto(`${BASE}/usage`, { waitUntil: 'domcontentloaded' })
    await page.waitForSelector('text=来源', { timeout: 20000 })
    await shot(page, '12-records-source')
  })
} finally {
  await browser.close()
}

const summary = {
  item: 'P3/P5/P6-FE/P7/P8/P9/P10',
  result: failures.length ? 'PARTIAL' : 'PASS',
  user_id: userId,
  model_aliases_sample: aliasSample,
  aggregate_total_cost: self.total_cost,
  market_chat_executor_count: withExecutor.length,
  steps: failures.length ? failures : undefined,
  screenshots: shots,
  checked_at: new Date().toISOString(),
  gateway,
}
const evidencePath = evidence('P356789', summary)
console.log(JSON.stringify({ ...summary, evidence: evidencePath }))
if (failures.length) process.exitCode = 1
