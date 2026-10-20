import { ArrowUpRight, ChevronRight, Timer } from 'lucide-react'
import type { CallRecordItem } from '@/api/billing'
import { CopyButton } from '@/components/CopyButton'
import { EmptyNote, Modal, StatusTag } from '@/components/ui'
import { useState } from 'react'
import { Link } from 'react-router-dom'

export function RecordTable({ records, compact = false }: { records: CallRecordItem[]; compact?: boolean }) {
  const [selected, setSelected] = useState<CallRecordItem | null>(null)
  return <>
    {!records.length ? <EmptyNote message="这里还没有调用记录，完成一次能力调试后，结果会自动出现在这里。"
      action={<Link className="text-link" to="/chat">发起第一次调用<ArrowUpRight size={13} /></Link>} /> :
      <div className="data-table-wrap"><table className="data-table records-table">
        <thead><tr><th>调用服务 / 模型</th><th>执行状态</th><th>积分消耗</th>{!compact && <th>耗时</th>}<th>调用时间</th><th><span className="sr-only">详情</span></th></tr></thead>
        <tbody>{records.map((item) => <tr key={item.id}>
          <td><div className="record-service"><span><strong>{item.service_name || '能力调用'}</strong><small>{item.model_name || '未标注模型'} · #{item.capability_id}</small></span></div></td>
          <td><StatusTag value={item.call_status} /></td><td><strong className="record-cost">{item.cost > 0 ? '-' + item.cost : '0'}</strong><span className="record-unit">积分</span></td>
          {!compact && <td><span className="record-duration"><Timer size={12} />{item.duration_ms.toLocaleString()} ms</span></td>}
          <td className="record-time">{item.create_time}</td><td><button className="icon-button" aria-label={'查看调用 ' + item.request_id} onClick={() => setSelected(item)}><ChevronRight size={15} /></button></td>
        </tr>)}</tbody></table></div>}
    <Modal open={!!selected} onClose={() => setSelected(null)} title="调用详情">
      {selected && <div className="record-detail">
        <div className="record-detail-heading"><StatusTag value={selected.call_status} /><span>{selected.create_time}</span></div>
        <dl><div><dt>服务</dt><dd>{selected.service_name}</dd></div><div><dt>能力编号</dt><dd>#{selected.capability_id}</dd></div>
          <div><dt>模型</dt><dd>{selected.model_name || '—'}</dd></div><div><dt>执行耗时</dt><dd>{selected.duration_ms} ms</dd></div>
          <div><dt>实际费用</dt><dd>{selected.cost} 积分</dd></div><div><dt>账单编号</dt><dd>#{selected.id}</dd></div></dl>
        <div className="request-id"><span>requestId</span><code>{selected.request_id}</code><CopyButton text={selected.request_id} label="复制 requestId" /></div>
        <p className="inline-note">排查调用时可提供此 requestId，关联执行结果、账单与积分变动。</p>
      </div>}
    </Modal>
  </>
}
