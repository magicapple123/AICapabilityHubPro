/** Run only against the QA environment created by run_leader_e2e.py --browser. */
import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import path from 'node:path'
import process from 'node:process'
import { chromium } from 'playwright'
import { runChatScenarios } from './chat-scenarios.ts'
import { runSettingsScenarios } from './settings-browser.ts'
import { runConsoleScenarios } from './console-browser.ts'

const base = process.env.PRO_E2E_WEB_URL
const username = process.env.PRO_E2E_USERNAME
const password = process.env.PRO_E2E_PASSWORD
const directory = process.env.PRO_E2E_EVIDENCE
const adminUsername = process.env.PRO_E2E_ADMIN_USERNAME
const adminPassword = process.env.PRO_E2E_ADMIN_PASSWORD
assert.ok(base && username && password && directory && adminUsername && adminPassword &&
  process.env.PRO_E2E_OWNED_QA?.startsWith('aihub-pro-leader-qa-'),
  'Use the isolated E2E launcher, not a developer database')
await mkdir(directory, { recursive: true })
const browser = await chromium.launch({ headless: true })
const options = { viewport: { width: 1440, height: 1000 }, timezoneId: 'Asia/Shanghai' }
const context = await browser.newContext(options)
const adminContext = await browser.newContext(options)
const page = await context.newPage()
const adminPage = await adminContext.newPage()
const errors: string[] = []
const checks: string[] = []
const suites: Record<string, string[]> = {}
let passed = false
let phase = 'chat'
page.on('pageerror', (error) => errors.push(error.message))
adminPage.on('pageerror', (error) => errors.push(error.message))
await context.route('**/picsum.photos/**', (route) => route.abort())
await adminContext.route('**/picsum.photos/**', (route) => route.abort())

try {
  await runChatScenarios(page, base, username, password, directory, errors, checks)
  suites.chat = checks.slice()
  phase = 'settings'
  await runSettingsScenarios(page, base, directory, checks)
  suites.settings = checks.slice(suites.chat.length)
  phase = 'console'
  await runConsoleScenarios(adminPage, page, base, adminUsername, adminPassword, directory, checks)
  suites.console = checks.slice(suites.chat.length + suites.settings.length)
  assert.deepEqual(errors, [])
  assert.ok(Object.values(suites).every((items) => items.length > 0))
  passed = true
  console.log(`Browser checks passed: ${checks.length}`)
} finally {
  await writeFile(path.join(directory, 'browser-summary.json'),
    JSON.stringify({ passed, phase, checks, suites, browserErrors: errors }, null, 2), { flag: 'wx' })
  await context.close()
  await adminContext.close()
  await browser.close()
}
