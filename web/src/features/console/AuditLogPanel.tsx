import { useCallback, useState } from 'react'
import { History, ShieldCheck } from 'lucide-react'
import { fetchAuditLogs, type AuditLog } from '@/api/audit'
import { EmptyNote, ErrorNote, Loading } from '@/components/ui'
import { useAsyncResource } from '@/hooks/useAsyncResource'

const RESOURCE_LABELS: Record<string, string> = {
  capability: '能力',
  category: '分类',
  user: '用户',
  points: '积分',
  apikey: '密钥',
}

const ACTION_LABELS: Record<string, string> = {
  create: '新建',
  update: '编辑',
  status: '上下架',
  delete: '删除',
  rollback: '回滚',
}

/** 只展示有变化的字段，避免整份配置铺满表格。 */
function diffFields(log: AuditLog): Array<{ key: string; before: string; after: string }> {
  const before = log.before_json ?? {}
  const after = log.after_json ?? {}
  const keys = new Set([...Object.keys(before), ...Object.keys(after)])
  const render = (value: unknown) => {
    if (value === null || value === undefined) return '—'
    if (typeof value === 'object') return JSON.stringify(value)
    return String(value)
  }
  return [...keys]
    .filter((key) => render(before[key]) !== render(after[key]))
    .map((key) => ({ key, before: render(before[key]), after: render(after[key]) }))
}

export function AuditLogPanel() {
  const [resourceType, setResourceType] = useState('')
  const load = useCallback(
    () => fetchAuditLogs({ resource_type: resourceType || undefined, page_size: 20 }),
    [resourceType],
  )
  const audit = useAsyncResource(load)
  const rows = audit.data?.list ?? []

  return (
    <>
      <div className="panel">
        <div className="panel-head">
          <h2><History size={16} /> 操作审计</h2>
          <div className="inline-form">
            <label className="muted text-xs" htmlFor="audit-resource">资源类型</label>
            <select
              id="audit-resource"
              value={resourceType}
              onChange={(event) => setResourceType(event.target.value)}
            >
              <option value="">全部</option>
              {Object.entries(RESOURCE_LABELS).map(([key, label]) => (
                <option key={key} value={key}>{label}</option>
              ))}
            </select>
          </div>
        </div>
        <p className="muted text-xs" style={{ padding: '0 16px 8px' }}>
          <ShieldCheck size={13} /> 审计记录只追加，任何接口都不能修改或删除历史记录。
        </p>
        {audit.loading && !audit.data ? <Loading label="正在读取审计记录…" /> : null}
        {audit.error ? <ErrorNote message={audit.error} onRetry={audit.reload} /> : null}
        {!audit.loading && !rows.length ? <EmptyNote message="还没有运营操作记录。" /> : null}
        {rows.length ? (
          <div className="data-table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>时间</th>
                  <th>操作人</th>
                  <th>资源</th>
                  <th>动作</th>
                  <th>变更</th>
                  <th>requestId</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((log) => (
                  <tr key={log.id}>
                    <td className="mono text-xs">{log.create_time}</td>
                    <td>
                      {log.operator_name || `#${log.operator_id}`}
                      <small className="muted"> #{log.operator_id}</small>
                    </td>
                    <td>
                      {RESOURCE_LABELS[log.resource_type] ?? log.resource_type}
                      <small className="muted"> #{log.resource_id}</small>
                    </td>
                    <td>{ACTION_LABELS[log.action] ?? log.action}</td>
                    <td>
                      <ul className="audit-diff">
                        {diffFields(log).map((item) => (
                          <li key={item.key}>
                            <code>{item.key}</code>
                            <span>{item.before}</span>
                            <span aria-hidden="true">→</span>
                            <strong>{item.after}</strong>
                          </li>
                        ))}
                        {!diffFields(log).length ? <li className="muted">无字段变化</li> : null}
                      </ul>
                    </td>
                    <td className="mono text-xs">{log.request_id || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </div>
    </>
  )
}
