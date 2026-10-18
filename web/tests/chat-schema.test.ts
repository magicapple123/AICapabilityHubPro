import assert from 'node:assert/strict'
import { test } from 'node:test'
import { buildInput, initialValues, positiveCapabilityId, schemaFields } from '../src/features/chat/schemaInput.ts'

const chatSchema = { type: 'object', properties: { messages: { type: 'array' } }, required: ['messages'] }

test('welcome text never enters model context; latest submitted user message is present', () => {
  const input = buildInput(chatSchema, { messages: 'new question' }, [
    { role: 'assistant', content: 'welcome', context: false },
    { role: 'user', content: 'previous question', context: true },
    { role: 'assistant', content: 'previous answer', context: true },
  ], 'chat-completions')
  assert.deepEqual(input.messages, [
    { role: 'user', content: 'previous question' },
    { role: 'assistant', content: 'previous answer' },
    { role: 'user', content: 'new question' },
  ])
})

test('history sent with a new message stays bounded', () => {
  const input = buildInput(chatSchema, { messages: 'latest' }, Array.from({ length: 80 }, (_, n) => ({
    role: 'user' as const, content: String(n), context: true,
  })), 'chat-completions')
  assert.equal((input.messages as unknown[]).length, 20)
})

test('summary input is separate from conversation history', () => {
  const schema = { type: 'object', properties: { text: { type: 'string' }, max_length: { type: 'integer', minimum: 30, maximum: 1000 } }, required: ['text'] }
  assert.deepEqual(buildInput(schema, { text: 'article', max_length: '50' }, [], 'long-summary'), { text: 'article', max_length: 50 })
  assert.throws(() => buildInput(schema, { text: '', max_length: '50' }, [], 'long-summary'))
  assert.throws(() => buildInput(schema, { text: 'article', max_length: '3.1' }, [], 'long-summary'))
  assert.throws(() => buildInput(schema, { text: 'article', max_length: '1001' }, [], 'long-summary'))
})

test('raw JSON only accepts object payloads', () => {
  assert.deepEqual(buildInput({}, { __json: '{"text":"article"}' }, [], 'long-summary'), { text: 'article' })
  assert.throws(() => buildInput({}, { __json: '[]' }, [], 'long-summary'))
})

test('invalid URL IDs cannot silently call the default capability', () => {
  for (const value of ['0', '-1', '1.5', 'abc', '1e2', '9007199254740992', '01']) assert.equal(positiveCapabilityId(value), null)
  assert.equal(positiveCapabilityId('2'), 2)
})

test('schema fields preserve required flags and typed defaults', () => {
  const schema = { properties: { text: { type: 'string' }, limit: { type: 'integer', default: 200 } }, required: ['text'] }
  assert.equal(schemaFields(schema)[0].required, true)
  assert.deepEqual(initialValues(schema), { text: '', limit: '200' })
})
