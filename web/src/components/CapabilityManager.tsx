import { App } from 'antd'
import { Pencil, Plus, Search, Trash2 } from 'lucide-react'
import { useCallback, useState } from 'react'
import { deleteCapability, fetchCategories, fetchManageCapabilities, updateCapabilityStatus, type CapabilityManageItem, type CapabilityStatus } from '@/api/capability'
import { EmptyNote, ErrorNote, Loading, Pager, StatusTag } from '@/components/ui'
import { CapabilityEditor } from '@/features/console/CapabilityEditor'
import { useAsyncResource } from '@/hooks/useAsyncResource'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'

const SIZE = 10
export function CapabilityManager({ onChanged }: { onChanged?: () => void }) {
  const [filters, setFilters] = useState({ status: '', category: '', keyword: '', page: 1 })
  const keyword = useDebouncedValue(filters.keyword.trim())
  const [creating, setCreating] = useState(false)
  const [editing, setEditing] = useState<CapabilityManageItem | null>(null)
  const [busy, setBusy] = useState<number | null>(null)
  const categories = useAsyncResource(fetchCategories)
  const load = useCallback(() => fetchManageCapabilities({
    status: (filters.status || undefined) as CapabilityStatus | undefined,
    category_id: Number(filters.category) || undefined, keyword: keyword || undefined, page: filters.page, page_size: SIZE,
  }), [filters.status, filters.category, filters.page, keyword])
  const data = useAsyncResource(load)
  const { modal, message } = App.useApp()
  const updated = () => { data.reload(); onChanged?.() }
  const remove = (item: CapabilityManageItem) => modal.confirm({
    title: '删除能力「' + item.name + '」？', content: '能力将从目录移除，历史调用记录保留。',
    okText: '确认删除', cancelText: '取消', okButtonProps: { danger: true },
    onOk: async () => {
      try { await deleteCapability(item.id); void message.success('能力已删除'); updated() }
      catch (cause) { void message.error(cause instanceof Error ? cause.message : '删除失败'); throw cause }
    },
  })
  const changeStatus = (item: CapabilityManageItem) => {
    const next = item.status === 'online' ? 'offline' : 'online'
    modal.confirm({
      title: (next === 'online' ? '上架' : '下架') + '能力「' + item.name + '」？',
      content: next === 'online' ? '上架后，该能力将出现在能力市场中。' : '下架后，该能力将不再出现在市场中，新的执行请求会被拒绝。',
      okText: '确认' + (next === 'online' ? '上架' : '下架'), cancelText: '取消',
      onOk: async () => {
        setBusy(item.id)
        try { await updateCapabilityStatus(item.id, next); updated(); void message.success('状态已更新') }
        catch (cause) { void message.error(cause instanceof Error ? cause.message : '状态更新失败'); throw cause }
        finally { setBusy(null) }
      },
    })
  }
  return <section className="panel"><div className="panel-head"><div><h2>能力目录</h2><p>维护能力参数、单价和可用状态</p></div><button className="button-primary" onClick={() => setCreating(true)}><Plus size={14} />登记新能力</button></div>
    <div className="management-filters"><label className="management-search"><Search size={14} /><input aria-label="搜索运营能力" placeholder="搜索能力名称或编码" value={filters.keyword} onChange={(e) => setFilters((old) => ({ ...old, keyword: e.target.value, page: 1 }))} /></label>
      <select aria-label="能力状态" className="form-control" value={filters.status} onChange={(e) => setFilters((old) => ({ ...old, status: e.target.value, page: 1 }))}><option value="">全部状态</option><option value="draft">草稿</option><option value="online">已上架</option><option value="offline">已下架</option></select>
      <select aria-label="能力分类" className="form-control" value={filters.category} onChange={(e) => setFilters((old) => ({ ...old, category: e.target.value, page: 1 }))}><option value="">全部分类</option>{categories.data?.list.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></div>
    {data.loading ? <Loading label="正在加载能力目录…" /> : data.error ? <div className="panel-body"><ErrorNote message={data.error} onRetry={data.reload} /></div> :
      !data.data?.list.length ? <EmptyNote message="没有符合条件的能力，试试调整筛选条件。" /> :
        <div className="data-table-wrap"><table className="data-table"><thead><tr><th>能力名称 / 编码</th><th>分类</th><th>积分单价</th><th>状态</th><th>更新时间</th><th>操作</th></tr></thead><tbody>{data.data.list.map((item) =>
          <tr key={item.id}><td><strong className="management-name">{item.name}</strong><code className="management-code">{item.code}</code></td><td>{item.category_name}</td><td>{item.price_per_call} 积分</td><td><StatusTag value={item.status} /></td><td className="record-time">{item.update_time}</td><td><div className="row-actions">
            <button className="text-link" disabled={busy === item.id} onClick={() => changeStatus(item)}>{item.status === 'online' ? '下架' : '上架'}</button><button className="icon-button" aria-label={'编辑能力' + item.name} onClick={() => setEditing(item)}><Pencil size={14} /></button><button className="icon-button danger-icon" aria-label={'删除能力' + item.name} onClick={() => remove(item)}><Trash2 size={14} /></button></div></td></tr>)}</tbody></table></div>}
    <Pager page={filters.page} pageSize={SIZE} total={data.data?.total ?? 0} onChange={(page) => setFilters((old) => ({ ...old, page }))} />
    {(creating || editing) && <CapabilityEditor item={editing} categories={categories.data?.list ?? []} onClose={() => { setCreating(false); setEditing(null) }} onSaved={() => { setCreating(false); setEditing(null); updated() }} />}
  </section>
}
