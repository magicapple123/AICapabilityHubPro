import { randomBytes } from 'node:crypto'
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs'
import { spawnSync } from 'node:child_process'
import { createRequire } from 'node:module'
import { resolve } from 'node:path'

export const root = resolve(import.meta.dirname, '../..')
export const outputDir = resolve(root, 'artifacts/verify-2026-11-03')
export const gateway = 'http://127.0.0.1:8080'
export const nonce = () => randomBytes(4).toString('hex')
export function assert(ok, message) { if (!ok) throw new Error(message) }
export function readEnv(path) {
  return Object.fromEntries(readFileSync(resolve(root, path), 'utf8').split(String.fromCharCode(10)).map(x => x.trim()).filter(x => /^[A-Z_]+=/.test(x)).map(x => {
    const at = x.indexOf('='); return [x.slice(0, at), x.slice(at + 1).trim()]
  }))
}
export function run(command, args, env = {}) {
  const result = spawnSync(command, args, { cwd: root, encoding: 'utf8', env: { ...process.env, ...env }, maxBuffer: 32 * 1024 * 1024 })
  assert(result.status === 0, command + ' failed exit=' + result.status)
  return result.stdout
}
export function compose(args, extraEnv = {}) {
  const current = spawnSync('docker', ['exec', 'aihub-verify-ai-chat', 'python', '-c', 'import os,json; print(json.dumps({k:os.environ.get(k,"") for k in ["PROVIDER_MASTER_KEY_V1","PROVIDER_ALLOWED_HOSTS"]}))'], { encoding: 'utf8' })
  const preserved = current.status === 0 ? JSON.parse(current.stdout) : {}
  return run('docker', ['compose', '--env-file', 'deploy/.env', '-p', 'aihub-pro-verify', '--profile', 'app', '-f', 'deploy/docker-compose.yml', '-f', 'deploy/docker-compose.verify.yml', ...args], {
    ...readEnv('deploy/.env'),
    PROVIDER_MASTER_KEY_V1: preserved.PROVIDER_MASTER_KEY_V1 || randomBytes(32).toString('base64'),
    PROVIDER_ALLOWED_HOSTS: preserved.PROVIDER_ALLOWED_HOSTS || 'api.deepseek.com,dashscope.aliyuncs.com', ...extraEnv,
  })
}
export async function api(path, { method = 'GET', body, token, base = gateway, headers = {} } = {}) {
  const response = await fetch(base + path, { method, headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: 'Bearer ' + token } : {}), ...headers }, ...(body === undefined ? {} : { body: JSON.stringify(body) }) })
  const payload = await response.json()
  return { status: response.status, ...payload }
}
export async function ok(path, options) {
  const result = await api(path, options)
  assert(result.status === 200 && result.code === 0, path + ': http=' + result.status + ' code=' + result.code)
  return result.data
}
export async function admin(item) {
  const username = 'live-' + item + '-admin-' + nonce(), password = randomBytes(24).toString('hex')
  run('C:/Program Files/Git/bin/bash.exe', ['scripts/bootstrap_stack.sh'], {
    COMPOSE_PROJECT_NAME: 'aihub-pro-verify', COMPOSE_OVERRIDE_FILE: 'deploy/docker-compose.verify.yml',
    BOOTSTRAP_ADMIN_USERNAME: username, BOOTSTRAP_ADMIN_PASSWORD: password, BOOTSTRAP_ADMIN_POINTS: '10000',
  })
  const login = await ok('/api/user/login', { method: 'POST', body: { username, password } })
  return { username, password, token: login.token, id: login.user?.id ?? login.id }
}
export async function runtimeConfig(config) {
  const form = new URLSearchParams({ dataId: 'ai-chat-service-model.json', group: 'DEFAULT_GROUP', content: JSON.stringify(config), type: 'json' })
  const response = await fetch('http://127.0.0.1:28848/nacos/v1/cs/configs', { method: 'POST', body: form })
  assert(response.ok, 'isolated runtime config update failed')
  await new Promise(r => setTimeout(r, 6500))
}
export function sql(query, container = 'aihub-verify-billing') {
  assert(query.trim().toUpperCase().startsWith('SELECT '), 'evidence SQL must be read only')
  const code = 'import json; from sqlalchemy import text; from app.db.session import engine; c=engine.connect(); print(json.dumps([dict(x) for x in c.execute(text(' + JSON.stringify(query) + ')).mappings()],default=str)); c.close()'
  return JSON.parse(run('docker', ['exec', container, 'python', '-c', code]))
}
export function evidence(item, data) {
  mkdirSync(outputDir, { recursive: true })
  const path = resolve(outputDir, item + '-' + nonce() + '-evidence.json')
  writeFileSync(path, JSON.stringify(data, null, 2), { flag: 'wx' })
  return path
}
export async function screenshotJson(item, data) {
  const require = createRequire(resolve(root, 'web/package.json'))
  const { chromium } = require('playwright')
  const browser = await chromium.launch({ headless: true })
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
    await page.goto('http://127.0.0.1:28088')
    await page.setContent('<html lang="zh"><meta charset="utf-8"><style>body{font:18px monospace;padding:30px;background:#f7f9fc;color:#182230}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style><h1></h1><pre></pre></html>')
    await page.locator('h1').evaluate((el, text) => { el.textContent = text }, item + ' · actual acceptance evidence')
    await page.locator('pre').evaluate((el, text) => { el.textContent = text }, JSON.stringify(data, null, 2))
    const path = resolve(outputDir, item + '-' + nonce() + '-results.png')
    await page.screenshot({ path, fullPage: true })
    return path
  } finally { await browser.close() }
}
