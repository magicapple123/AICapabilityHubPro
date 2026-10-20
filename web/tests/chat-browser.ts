/** Run only against the QA environment created by run_leader_e2e.py --browser. */
import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import path from 'node:path'
import process from 'node:process'
import { chromium } from 'playwright'
import { runChatScenarios } from './chat-scenarios.ts'

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
  await runChatScenarios(page, base, username, password, directory, errors, checks)
  await writeFile(path.join(directory, 'browser-summary.json'), JSON.stringify({ passed: true, checks, browserErrors: errors }, null, 2), { flag: 'wx' })
  console.log(`Browser checks passed: ${checks.length}`)
} finally {
  await context.close()
  await browser.close()
}
