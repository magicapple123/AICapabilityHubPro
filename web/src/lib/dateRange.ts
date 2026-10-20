export function localDate(value: Date) {
  return [value.getFullYear(), String(value.getMonth() + 1).padStart(2, '0'), String(value.getDate()).padStart(2, '0')].join('-')
}
export function dateRange(days: number) {
  const end = new Date()
  const start = new Date(end)
  start.setDate(start.getDate() - days + 1)
  return { start_date: localDate(start), end_date: localDate(end) }
}
export function formatNumber(value: number | undefined | null) {
  return value === undefined || value === null ? '—' : value.toLocaleString('zh-CN')
}
