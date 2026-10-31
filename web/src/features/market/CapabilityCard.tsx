import { ArrowRight } from 'lucide-react'
import { Link } from 'react-router-dom'
import type { MarketCapability } from '@/api/capability'

export function CapabilityCard({ item, supported, pending, onDetail }: {
  item: MarketCapability; supported: boolean; pending: boolean; onDetail: () => void
}) {
  return <article className="capability-card">
    <div className="capability-card-top"><span className="capability-category">{item.category_name}</span>
      <span className={'availability ' + (supported ? 'ready' : '')}><i />{pending ? '读取状态' : supported ? '支持调试' : '暂无执行器'}</span></div>
    <div className="capability-heading"><h2>{item.name}</h2></div>
    <p className="capability-code">{item.code}</p><p className="capability-description">{item.description || '暂无描述。'}</p>
    <div className="capability-card-bottom"><div><strong>{item.price_per_call}</strong><span>积分 / 次</span></div>
      <button className="capability-detail-button" aria-label={'查看' + item.name + '详情'} onClick={onDetail}>参数说明</button></div>
    {supported ? <Link className="capability-launch" to={'/chat?capability_id=' + item.id}>开始调试<ArrowRight size={13} /></Link> :
      <button className="capability-launch" disabled title={pending ? '正在读取支持的执行器' : '该能力暂无兼容的执行器'}>{pending ? '正在检查…' : '暂不可调试'}</button>}
  </article>
}
