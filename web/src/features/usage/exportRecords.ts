import type { CallRecordItem } from '@/api/billing'

const ENTRYPOINTS: Record<string, string> = {
  web: '网页调试', platform_api: '平台 API', openai_compat: 'OpenAI 兼容',
}

/** P6：来源标记；历史记录为空串，前端统一显示 `—`。 */
export function entrypointLabel(value?: string | null) {
  if (!value) return '—'
  return ENTRYPOINTS[value] ?? value
}

/** P6：历史记录的 `api_key_id` 为 null（网页调试台 / 加列前的数据），导出写 `—` 且不报错。 */
function keyLabel(value?: number | null) {
  return value ? '#' + value : '—'
}

function cell(value: string | number) {
  let text = String(value)
  if (typeof value === 'string' && /^[=+\-@\t\r]/.test(text)) text = "'" + text
  return '"' + text.replace(/"/g, '""') + '"'
}
export function exportRecords(records: CallRecordItem[]) {
  const rows: (string | number)[][] = [
    ['账单编号', 'requestId', '能力编号', '服务', '模型', '来源', 'Key 编号', '状态', '积分', '耗时(ms)', '调用时间'],
    ...records.map((item) => [
      item.id, item.request_id, item.capability_id, item.service_name, item.model_name,
      entrypointLabel(item.entrypoint), keyLabel(item.api_key_id),
      item.call_status, item.cost, item.duration_ms, item.create_time,
    ]),
  ]
  const blob = new Blob(['\ufeff' + rows.map((row) => row.map(cell).join(',')).join('\r\n')], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = '调用记录-' + new Date().toISOString().slice(0, 10) + '.csv'
  link.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}
