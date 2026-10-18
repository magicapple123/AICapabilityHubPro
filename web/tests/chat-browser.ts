/** Run only against the QA environment created by run_leader_e2e.py --browser. */
import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import path from 'node:path'
import process from 'node:process'
import { chromium } from 'playwright'

const base = process.env.PRO_E2E_WEB_URL
const username = process.env.PRO_E2E_USERNAME
const password = process.env.PRO_E2E_PASSWORD
const directory = process.env.PRO_E2E_EVIDENCE
assert.ok(base && username && password && directory, 'Use the isolated E2E launcher, not a developer database')
await mkdir(directory, { recursive: true })
const browser = await chromium.launch({ headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
const page = await context.newPage()
const errors: string[] = []
const checks: string[] = []
page.on('pageerror', (error) => errors.push(error.message))
await context.route('**/picsum.photos/**', (route) => route.abort())

try {
  await page.goto(base + '/login')
  await page.getByPlaceholder('3~32 位字母 / 数字 / 下划线 / 连字符').fill(username)
  await page.locator('input[type="password"]').fill(password)
  await page.locator('form').getByRole('button').click()
  await page.waitForURL((url) => url.pathname === '/')
  checks.push('real login through the Vite proxy')
  await page.goto(base + '/chat?capability_id=1')
  await page.getByRole('button', { name: '发送消息', exact: true }).waitFor()
  assert.equal(await page.getByRole('combobox', { name: '调用能力' }).inputValue(), '1')
  await page.getByPlaceholder('输入本轮消息，已有对话会自动作为上下文。').fill('浏览器验证聊天能力与实际费用')
  const chatResponse = page.waitForResponse((response) => response.url().includes('/api/chat/completions') && response.request().method() === 'POST')
  await page.getByRole('button', { name: '发送消息', exact: true }).click()
  const chat = await (await chatResponse).json()
  assert.equal(chat.code, 0)
  assert.equal(chat.data.capability_id, 1)
  assert.equal(chat.data.cost, 5)
  await page.getByRole('status').getByText('requestId:', { exact: false }).waitFor()
  assert.ok((await page.getByRole('status').innerText()).includes(chat.requestId))
  await page.evaluate(() => window.scrollTo(0, 0))
  await page.screenshot({ path: path.join(directory, 'chat-desktop.png'), fullPage: true })
  checks.push('chat form, real completion, 5-point receipt and trace visible')

  await page.getByRole('combobox', { name: '调用能力' }).selectOption('2')
  await page.getByRole('button', { name: '生成摘要', exact: true }).waitFor()
  assert.equal(await page.getByRole('button', { name: '生成摘要', exact: true }).isEnabled(), true)
  await page.getByLabel('待摘要文本', { exact: false }).fill('浏览器验收需覆盖聊天和摘要。两种能力应按各自单价扣减积分，并显示追踪信息。')
  const summaryResponse = page.waitForResponse((response) => response.url().includes('/api/chat/completions') && response.request().method() === 'POST')
  await page.getByRole('button', { name: '生成摘要', exact: true }).click()
  const summary = await (await summaryResponse).json()
  assert.equal(summary.code, 0)
  assert.equal(summary.data.capability_id, 2)
  assert.equal(summary.data.cost, 3)
  await page.getByRole('status').getByText('requestId:', { exact: false }).waitFor()
  await page.evaluate(() => window.scrollTo(0, 0))
  await page.screenshot({ path: path.join(directory, 'summary-desktop.png'), fullPage: true })
  checks.push('URL selection switches to the summary schema and 3-point receipt')

  await page.getByRole('combobox', { name: '调用能力' }).selectOption('4')
  await page.getByText('该能力暂无兼容执行器或参数 Schema，当前不可体验。请选择聊天或文本摘要。').waitFor()
  assert.equal(await page.getByRole('button', { name: '发送消息', exact: true }).isDisabled(), true)
  checks.push('unsupported published capability cannot be submitted')
  await page.goto(base + '/chat?capability_id=99999')
  await page.getByText('能力不存在或已下线', { exact: false }).waitFor()
  assert.equal(await page.getByRole('button', { name: '发送消息', exact: true }).count(), 0)
  checks.push('unknown capability is shown as an error, never a default chat fallback')

  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto(base + '/chat?capability_id=2')
  await page.getByRole('button', { name: '生成摘要', exact: true }).waitFor()
  const size = await page.evaluate(() => ({ width: window.innerWidth, content: document.documentElement.scrollWidth }))
  assert.ok(size.content <= size.width + 1, `Horizontal overflow: ${size.content}/${size.width}`)
  const textarea = await page.getByLabel('待摘要文本', { exact: false }).boundingBox()
  assert.ok(textarea && textarea.x >= 0 && textarea.x + textarea.width <= 390,
    'The mobile textarea must be visible within the viewport, not clipped by an overflow container')
  await page.screenshot({ path: path.join(directory, 'summary-mobile.png'), fullPage: true })
  checks.push('390px mobile layout stays within viewport')
  assert.deepEqual(errors, [])
  checks.push('no uncaught browser errors')
  await writeFile(path.join(directory, 'browser-summary.json'), JSON.stringify({ passed: true, checks, browserErrors: errors }, null, 2), { flag: 'wx' })
  console.log(`Browser checks passed: ${checks.length}`)
} finally {
  await context.close()
  await browser.close()
}
