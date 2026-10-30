import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  MAX_ACCOUNTS,
  decodeRole,
  isExpired,
  removeAccount,
  upsertAccount,
  type SavedAccount,
} from '../src/stores/accountVault.ts'

function account(username: string, extra: Partial<SavedAccount> = {}): SavedAccount {
  return {
    username,
    displayName: username,
    role: 'user',
    userId: '1',
    token: 'token-' + username,
    expireAt: '',
    savedAt: 1,
    ...extra,
  }
}

const jwt = (payload: object) =>
  'header.' + Buffer.from(JSON.stringify(payload)).toString('base64url') + '.signature'

test('role is decoded from the JWT payload, malformed tokens fall back to user', () => {
  assert.equal(decodeRole(jwt({ role: 'admin' })), 'admin')
  assert.equal(decodeRole(jwt({ role: 'user' })), 'user')
  assert.equal(decodeRole(jwt({ sub: '1' })), 'user')
  assert.equal(decodeRole('not-a-jwt'), 'user')
})

test('upsert keeps the most recent account first and never duplicates', () => {
  const first = upsertAccount([], account('demo'))
  const second = upsertAccount(first, account('admin'))
  assert.deepEqual(second.map((item) => item.username), ['admin', 'demo'])

  const refreshed = upsertAccount(second, account('demo', { token: 'new-token' }))
  assert.deepEqual(refreshed.map((item) => item.username), ['demo', 'admin'])
  assert.equal(refreshed[0].token, 'new-token')
})

test('account vault is capped to the most recent entries', () => {
  let list: SavedAccount[] = []
  for (let index = 0; index < MAX_ACCOUNTS + 3; index += 1) {
    list = upsertAccount(list, account('user' + index))
  }
  assert.equal(list.length, MAX_ACCOUNTS)
  assert.equal(list[0].username, 'user' + (MAX_ACCOUNTS + 2))
})

test('remove drops only the requested account', () => {
  const list = upsertAccount(upsertAccount([], account('demo')), account('admin'))
  assert.deepEqual(removeAccount(list, 'demo').map((item) => item.username), ['admin'])
  assert.deepEqual(removeAccount(list, 'missing').map((item) => item.username), ['admin', 'demo'])
})

test('expiry compares against the backend local timestamp', () => {
  const fixed = new Date('2026-10-31T08:00:00').getTime()
  assert.equal(isExpired(account('a', { expireAt: '2026-10-31 07:59:59' }), fixed), true)
  assert.equal(isExpired(account('a', { expireAt: '2026-10-31 08:00:01' }), fixed), false)
  assert.equal(isExpired(account('a', { expireAt: '' }), fixed), false)
})
