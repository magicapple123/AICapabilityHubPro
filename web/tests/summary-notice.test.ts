import assert from 'node:assert/strict'
import { test } from 'node:test'
import { SUMMARY_NOTICE, looksLikeQuestion } from '../src/features/chat/summaryNotice.ts'

/** 与实现保持一致的判定上限，用于在边界用例里自检字符串长度。 */
const QUESTION_MAX_CHARS = 120

test('empty or whitespace-only input is never a question', () => {
  for (const value of ['', ' ', '   ', '\n\t\r\n', ' \u3000 ']) {
    assert.equal(looksLikeQuestion(value), false, JSON.stringify(value) + ' should not be a question')
  }
})

test('the reported input "我想知道python装饰器怎么写" is detected as a question', () => {
  assert.equal(looksLikeQuestion('我想知道python装饰器怎么写'), true)
})

test('a trailing question mark is detected for full-width, half-width and trailing spaces', () => {
  for (const value of ['装饰器怎么用？', 'how to use a decorator?', '怎么用？ ', '  怎么用？  ']) {
    assert.equal(looksLikeQuestion(value), true, JSON.stringify(value) + ' should be a question')
  }
})

test('an english question without any chinese marker is detected by its trailing mark', () => {
  assert.equal(looksLikeQuestion('what is API?'), true)
})

test('a short statement weekly report is treated as material', () => {
  const report = '本周完成登录联调与能力目录对接，下周计划补充异常场景测试。'
  assert.ok(Array.from(report).length <= QUESTION_MAX_CHARS)
  assert.equal(looksLikeQuestion(report), false)
})

test('a long document containing 如何 is material and is not reported', () => {
  const document = '以下为项目组本周的技术说明，用于同步工程实践与评审记录。'
    + '本段用于补足文档篇幅，仅作背景材料。'.repeat(4)
    + '其中第一节讨论了如何拆分前端模块并统一交互规范。'
  assert.ok(Array.from(document).length > QUESTION_MAX_CHARS, 'fixture must exceed the character limit')
  assert.equal(looksLikeQuestion(document), false)
})

test('the 120 character boundary still reports a question, 121 does not', () => {
  const atLimit = '如何' + 'A'.repeat(QUESTION_MAX_CHARS - 2)
  const overLimit = '如何' + 'A'.repeat(QUESTION_MAX_CHARS - 1)
  assert.equal(Array.from(atLimit).length, QUESTION_MAX_CHARS)
  assert.equal(Array.from(overLimit).length, QUESTION_MAX_CHARS + 1)
  assert.equal(looksLikeQuestion(atLimit), true)
  assert.equal(looksLikeQuestion(overLimit), false)
})

test('a single character marker 吗 is enough to report a question', () => {
  assert.equal(looksLikeQuestion('吗'), true)
})

test('length is counted by code point, so astral characters are not double counted', () => {
  const plain = '🙂'.repeat(121)
  assert.equal(plain.length, 242, 'fixture must be a surrogate pair string')
  assert.equal(Array.from(plain).length, 121)
  assert.equal(looksLikeQuestion(plain), false)

  // 120 码点、但 UTF-16 长度远大于 120：若按 .length 计数会被误判为长文档。
  const withinLimit = '🙂'.repeat(119) + '？'
  assert.equal(Array.from(withinLimit).length, QUESTION_MAX_CHARS)
  assert.ok(withinLimit.length > QUESTION_MAX_CHARS)
  assert.equal(looksLikeQuestion(withinLimit), true)

  // 121 码点：超限，即使以问号结尾也不再提示。
  assert.equal(looksLikeQuestion('🙂'.repeat(120) + '？'), false)
})

test('the summary notice is present and stays factual', () => {
  assert.equal(typeof SUMMARY_NOTICE, 'string')
  assert.ok(SUMMARY_NOTICE.trim().length > 0)
  assert.equal(SUMMARY_NOTICE.includes('!'), false)
  assert.equal(SUMMARY_NOTICE.includes('！'), false)
  assert.ok(SUMMARY_NOTICE.includes('摘要'))
})
