/** Bounded real-HTTP browser assertions. Never log credential bodies or auth state. */
import assert from 'node:assert/strict'
import type { APIResponse, Locator, Page, Response } from 'playwright'

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

export function record(value: unknown): Record<string, unknown> {
  assert.ok(isRecord(value), 'Expected a JSON object')
  return value
}

export function records(value: unknown): Record<string, unknown>[] {
  assert.ok(Array.isArray(value), 'Expected a JSON array')
  const values: unknown[] = value
  return values.map(record)
}

export async function result(response: Response | APIResponse, expectedCode = 0) {
  assert.equal(response.status(), 200, 'Unexpected real HTTP status')
  let parsed: unknown
  try { parsed = await response.json() } catch { throw new Error('Invalid Result JSON') }
  const body = record(parsed)
  assert.equal(body.code, expectedCode, 'Unexpected business result code')
  assert.ok(typeof body.requestId === 'string' && body.requestId.length > 0)
  return { body, headers: response.headers() }
}

export function responseFor(page: Page, method: string, pathname: string) {
  return page.waitForResponse((response) => new URL(response.url()).pathname === pathname &&
    response.request().method() === method)
}

export async function submit(page: Page, method: string, pathname: string, action: () => Promise<unknown>) {
  const response = responseFor(page, method, pathname)
  await action()
  return result(await response)
}

async function authorization(page: Page) {
  const saved = await page.evaluate(() => localStorage.getItem('ai-capability-auth'))
  assert.ok(saved, 'Expected a real logged-in browser identity')
  const parsed: unknown = JSON.parse(saved)
  const token = record(record(parsed).state).token
  assert.ok(typeof token === 'string' && token.length > 20, 'Missing signed JWT')
  return { Authorization: 'Bearer ' + token }
}

export async function request(page: Page, method: string, pathname: string, options: {
  data?: unknown; code?: number; anonymous?: boolean; headers?: Record<string, string>
} = {}) {
  const headers = { ...(options.anonymous ? {} : await authorization(page)), ...options.headers }
  let response: APIResponse
  try {
    response = await page.request.fetch(new URL(pathname, page.url()).toString(), {
      method, data: options.data, headers, timeout: 15_000,
    })
  } catch { throw new Error('QA HTTP transport failed; credential details withheld') }
  return result(response, options.code ?? 0)
}

export async function login(page: Page, base: string, username: string, password: string) {
  try {
    await page.goto(base + '/login')
    await page.getByRole('textbox', { name: '账号', exact: true }).fill(username)
    await page.locator('input[type="password"]').fill(password)
    await submit(page, 'POST', '/api/user/login', () =>
      page.getByRole('button', { name: '登录工作空间', exact: true }).click())
    await page.waitForURL((url) => url.pathname === '/')
  } catch { throw new Error('QA real login failed; credential details withheld') }
}

export async function viewport(page: Page, target: Locator) {
  const size = await page.evaluate(() => ({ width: innerWidth, content: document.documentElement.scrollWidth }))
  assert.ok(size.content <= size.width + 1, 'The page must not overflow horizontally')
  const box = await target.boundingBox()
  assert.ok(box && box.x >= 0 && box.x + box.width <= size.width + 1,
    'The primary control must be within the viewport, not clipped')
}

export function shanghaiDate(offsetMs: number) {
  return new Date(Date.now() + 8 * 3_600_000 + offsetMs).toISOString().slice(0, 16)
}

export async function assertSecretAbsent(page: Page, secret: string) {
  const storage = await page.evaluate(() => JSON.stringify({
    local: Object.entries(localStorage), session: Object.entries(sessionStorage), cookie: document.cookie,
  }))
  assert.ok(!storage.includes(secret), 'The full Secret must not enter browser storage')
  assert.ok(!page.url().includes(secret), 'The full Secret must not enter a URL')
  assert.ok(!(await page.locator('body').innerText()).includes(secret), 'The closed Secret must not remain visible')
}
