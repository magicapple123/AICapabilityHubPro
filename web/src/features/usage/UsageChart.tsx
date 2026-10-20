import { useId, useMemo, useState } from 'react'
import type { UsageData } from '@/api/billing'
import { localDate } from '@/lib/dateRange'

export function UsageChart({ usage }: { usage: UsageData }) {
  const gradient = useId().replace(/:/g, '')
  const [active, setActive] = useState<number | null>(null)
  const days = useMemo(() => {
    const start = new Date(usage.start_date + 'T00:00:00')
    const end = new Date(usage.end_date + 'T00:00:00')
    const counts = new Map(usage.by_day.map((day) => [day.stat_date.slice(0, 10), day]))
    const values = []
    while (start <= end && values.length < 92) {
      const date = localDate(start)
      values.push(counts.get(date) ?? { stat_date: date, call_count: 0, total_cost: 0 })
      start.setDate(start.getDate() + 1)
    }
    return values
  }, [usage])
  const maximum = Math.max(4, ...days.map((day) => day.call_count))
  const selected = active === null ? null : days[active]
  const y = (count: number) => 150 - count / maximum * 122
  const x = (index: number) => days.length < 2 ? 280 : 30 + index / (days.length - 1) * 530
  const line = days.map((day, index) => (index === 0 ? 'M' : 'L') + x(index) + ',' + y(day.call_count)).join(' ')
  const area = line ? line + ' L' + x(days.length - 1) + ',150 L' + x(0) + ',150 Z' : ''
  return <div className="usage-chart">
    <div className="chart-summary"><span><i />调用次数</span><strong>{selected ? selected.stat_date.slice(5) + ' · ' + selected.call_count + ' 次 / ' + selected.total_cost + ' 积分' : '共 ' + usage.summary.call_count.toLocaleString() + ' 次调用'}</strong></div>
    <div className="chart-plot"><div className="chart-y-labels" aria-hidden="true">{[4, 3, 2, 1, 0].map((tick) => <span key={tick}>{Math.round(maximum * tick / 4)}</span>)}</div>
    <svg viewBox="0 0 590 184" role="img" aria-label="每日调用次数折线图" preserveAspectRatio="none">
      <defs><linearGradient id={gradient} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#798477" stopOpacity=".28" /><stop offset="100%" stopColor="#798477" stopOpacity=".02" /></linearGradient></defs>
      {[0, 1, 2, 3, 4].map((tick) => <g key={tick}><line x1="30" x2="560" y1={28 + tick * 30.5} y2={28 + tick * 30.5} stroke="#e9eae5" strokeDasharray="4 5" /></g>)}
      {area && <path d={area} fill={'url(#' + gradient + ')'} />}
      {line && <path d={line} fill="none" stroke="#6c7b69" strokeWidth="2.5" strokeLinejoin="round" strokeLinecap="round" />}
      {days.map((day, index) => <g key={day.stat_date} onMouseEnter={() => setActive(index)} onMouseLeave={() => setActive(null)}>
        <rect x={x(index) - 10} y="20" width="20" height="140" fill="transparent" />
        <circle cx={x(index)} cy={y(day.call_count)} r={active === index ? 4.5 : 3} fill="#fff" stroke="#6c7b69" strokeWidth="2" />
        <title>{day.stat_date + '：' + day.call_count + ' 次，' + day.total_cost + ' 积分'}</title>
      </g>)}
    </svg></div>
    <div className="chart-x-labels" aria-hidden="true">{days.filter((_, index) => days.length <= 8 || index % Math.ceil(days.length / 6) === 0 || index === days.length - 1).map((day) => <span key={day.stat_date}>{day.stat_date.slice(5).replace('-', '/')}</span>)}</div>
    <details className="chart-data"><summary>查看每日数据</summary><div className="chart-data-grid">
      {days.map((day) => <span key={day.stat_date}>{day.stat_date.slice(5)}<b>{day.call_count} 次</b></span>)}
    </div></details>
  </div>
}
