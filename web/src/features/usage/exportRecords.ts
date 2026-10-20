import type { CallRecordItem } from '@/api/billing'

function cell(value: string | number) {
  let text = String(value)
  if (typeof value === 'string' && /^[=+\-@\t\r]/.test(text)) text = "'" + text
  return '"' + text.replace(/"/g, '""') + '"'
}
export function exportRecords(records: CallRecordItem[]) {
  const rows: (string | number)[][] = [['账单编号', 'requestId', '能力编号', '服务', '模型', '状态', '积分', '耗时(ms)', '调用时间'],
    ...records.map((item) => [item.id, item.request_id, item.capability_id, item.service_name, item.model_name, item.call_status, item.cost, item.duration_ms, item.create_time])]
  const blob = new Blob(['\ufeff' + rows.map((row) => row.map(cell).join(',')).join('\r\n')], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = '调用记录-' + new Date().toISOString().slice(0, 10) + '.csv'
  link.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}
