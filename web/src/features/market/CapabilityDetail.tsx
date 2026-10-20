import { ArrowUpRight, Code2 } from 'lucide-react'
import { useCallback } from 'react'
import { Link } from 'react-router-dom'
import type { MarketCapability } from '@/api/capability'
import { Modal, ErrorNote, Loading } from '@/components/ui'
import { useAsyncResource } from '@/hooks/useAsyncResource'
import { fetchMarketDetail } from '@/features/chat/api'
import { schemaConstraintLines, schemaFields } from '@/features/chat/schemaInput'

export function CapabilityDetail({ item, supported, onClose }: { item: MarketCapability; supported: boolean; onClose: () => void }) {
  const load = useCallback(() => fetchMarketDetail(item.id), [item.id])
  const detail = useAsyncResource(load)
  const fields = detail.data ? schemaFields(detail.data.param_schema ?? {}) : []
  return <Modal title={item.name} open onClose={onClose}>
    <div className="detail-meta"><span>{item.category_name}</span><span>已上架</span><code>{item.code}</code><strong>{item.price_per_call} 积分 / 次</strong></div>
    <p className="detail-description">{item.description}</p>
    <h3 className="detail-section-title"><Code2 size={15} />输入参数</h3>
    {detail.loading ? <Loading /> : detail.error ? <ErrorNote message={detail.error} onRetry={detail.reload} /> :
      <div className="schema-detail-list">{fields.length ? fields.map((field) => {
        const constraints = schemaConstraintLines(field.schema)
        return <div key={field.name}><span><strong>{field.title}</strong><code>{field.name}</code></span>
          <span>{field.type}<b>{field.required ? '必填' : '可选'}</b></span>
          {constraints.length > 0 && <p className="schema-constraints">{constraints.join('；')}</p>}</div>
      }) : <p className="muted">该能力尚未提供结构化输入说明。</p>}</div>}
    <p className="inline-note">实际执行前会重新核对能力状态、参数与目录价格。模型故障导致的降级执行不计费。</p>
    <div className="detail-action">{supported ? <Link className="button-primary" to={'/chat?capability_id=' + item.id}>调试此能力<ArrowUpRight size={14} /></Link> :
      <button className="button-secondary" disabled>暂无兼容执行器</button>}</div>
  </Modal>
}
