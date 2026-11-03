import { App } from 'antd'
import { useCallback, useState } from 'react'
import { History, RotateCcw, ShieldCheck } from 'lucide-react'
import { fetchAuditLogs, type AuditLog } from '@/api/audit'
import { rollbackCapability } from '@/api/capability'
import { EmptyNote, ErrorNote, Loading } from '@/components/ui'
import { CopyButton } from '@/components/CopyButton'
import { useAsyncResource } from '@/hooks/useAsyncResource'
import './audit-log.css'

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

function compactValue(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (Array.isArray(value)) return `[…] ${value.length} 项`
  if (typeof value === 'object') return `{…} ${Object.keys(value).length} 个字段`
  const text = String(value)
  return text.length > 40 ? `${text.slice(0, 40)}…` : text
}

/** 每行只计算一次差异；完整快照留在可展开区域。 */
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
    .map((key) => ({ key, before: compactValue(before[key]), after: compactValue(after[key]) }))
}

export function AuditLogPanel() {
  const [resourceType, setResourceType] = useState('')
  const [rollbackBusy, setRollbackBusy] = useState<number | null>(null)
  const { message, modal } = App.useApp()
  const load = useCallback(
    () => fetchAuditLogs({ resource_type: resourceType || undefined, page_size: 20 }),
    [resourceType],
  )
  const audit = useAsyncResource(load)
  const rows = audit.data?.list ?? []

  /** 只有能力的「编辑 / 上下架」才有可回滚的字段快照。 */
  const canRollback = (log: AuditLog) =>
    log.resource_type === 'capability' && (log.action === 'update' || log.action === 'status')

  const rollback = (log: AuditLog) => modal.confirm({
    title: `回滚能力 #${log.resource_id}？`,
    content: `将以审计 #${log.id} 的变更前快照为准回填字段，回滚本身也会写一条新审计。`,
    okText: '确认回滚', cancelText: '取消', okButtonProps: { danger: true },
    onOk: async () => {
      setRollbackBusy(log.id)
      try {
        await rollbackCapability(Number(log.resource_id), log.id)
        void message.success('已回滚到该版本')
        audit.reload()
      } catch (cause) {
        void message.error(cause instanceof Error ? cause.message : '回滚失败')
        throw cause
      } finally {
        setRollbackBusy(null)
      }
    },
  })

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
          <div className="data-table-wrap audit-table-wrap">
            <table className="data-table data-table--audit">
              <colgroup>
                <col className="audit-col-time" />
                <col className="audit-col-operator" />
                <col className="audit-col-resource" />
                <col className="audit-col-action" />
                <col />
                <col className="audit-col-request" />
                <col className="audit-col-controls" />
              </colgroup>
              <thead>
                <tr>
                  <th>时间</th>
                  <th className="audit-operator">操作人</th>
                  <th>资源</th>
                  <th>动作</th>
                  <th>变更</th>
                  <th>requestId</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((log) => {
                  const changes = diffFields(log)
                  const [date, time = ''] = log.create_time.replace('T', ' ').split(' ')
                  const operator = `${log.operator_name || '用户'} #${log.operator_id}`
                  const requestId = log.request_id || ''
                  return (
                  <tr key={log.id}>
                    <td className="audit-time mono text-xs" data-label="时间" title={log.create_time}>
                      <span>{date.slice(5)}</span><span>{time.slice(0, 8)}</span>
                    </td>
                    <td className="audit-operator" data-label="操作人">
                      <div>{log.operator_name || `#${log.operator_id}`}
                        <small className="muted"> #{log.operator_id}</small></div>
                    </td>
                    <td data-label="资源" title={`操作人：${operator}`}>
                      <div>{RESOURCE_LABELS[log.resource_type] ?? log.resource_type}
                        <small className="muted"> #{log.resource_id}</small></div>
                    </td>
                    <td data-label="动作">{ACTION_LABELS[log.action] ?? log.action}</td>
                    <td className="audit-changes" data-label="变更">
                      <ul className="audit-diff audit-changes-preview">
                        {changes.slice(0, 3).map((item) => (
                          <li key={item.key}>
                            <code>{item.key}</code>
                            <div><span>{item.before}</span><span aria-hidden="true"> → </span><strong>{item.after}</strong></div>
                          </li>
                        ))}
                        {!changes.length ? <li className="muted">无字段变化</li> : null}
                      </ul>
                      {changes.length ? <details className="audit-snapshots">
                        <summary>{changes.length > 3 ? `还有 ${changes.length - 3} 项 · ` : ''}展开完整快照</summary>
                        <section aria-label={`审计 ${log.id} 的完整快照`}>
                          <h3>变更前</h3><pre>{JSON.stringify(log.before_json ?? {}, null, 2)}</pre>
                          <h3>变更后</h3><pre>{JSON.stringify(log.after_json ?? {}, null, 2)}</pre>
                        </section>
                      </details> : null}
                    </td>
                    <td className="audit-request mono text-xs" data-label="requestId">
                      {requestId ? <div><span title={requestId}>{requestId.length > 16 ? `${requestId.slice(0, 8)}…${requestId.slice(-4)}` : requestId}</span>
                        <CopyButton text={requestId} label="复制完整 requestId" compact /></div> : '—'}
                    </td>
                    <td data-label="操作">
                      {canRollback(log) ? (
                        <button className="text-button" disabled={rollbackBusy === log.id} onClick={() => rollback(log)}>
                          <RotateCcw size={12} /> {rollbackBusy === log.id ? '回滚中…' : '回滚'}
                        </button>
                      ) : <span className="muted">—</span>}
                    </td>
                  </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        ) : null}
      </div>
    </>
  )
}
