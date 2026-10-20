import { App } from 'antd'
import { Pencil, Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { deleteCategory, fetchCategories, type CategoryItem } from '@/api/capability'
import { ErrorNote, EmptyNote, Loading, StatusTag } from '@/components/ui'
import { useAsyncResource } from '@/hooks/useAsyncResource'
import { CategoryEditor } from '@/features/console/CategoryEditor'

export function CategoryManager({ onChanged }: { onChanged?: () => void }) {
  const data = useAsyncResource(fetchCategories)
  const [creating, setCreating] = useState(false)
  const [editing, setEditing] = useState<CategoryItem | null>(null)
  const { modal, message } = App.useApp()
  const updated = () => { data.reload(); onChanged?.(); setCreating(false); setEditing(null) }
  const remove = (item: CategoryItem) => modal.confirm({
    title: '删除分类「' + item.name + '」？', content: '分类下仍有能力时无法删除。删除后的分类不会出现在目录中。',
    okText: '确认删除', cancelText: '取消', okButtonProps: { danger: true },
    onOk: async () => {
      try { await deleteCategory(item.id); void message.success('分类已删除'); data.reload(); onChanged?.() }
      catch (cause) { void message.error(cause instanceof Error ? cause.message : '删除失败'); throw cause }
    },
  })
  return <section className="panel"><div className="panel-head"><div><h2>能力分类</h2><p>使用分类组织能力，让目录更容易浏览</p></div><button className="button-primary" onClick={() => setCreating(true)}><Plus size={14} />新增分类</button></div>
    {data.loading ? <Loading label="正在读取分类…" /> : data.error ? <div className="panel-body"><ErrorNote message={data.error} onRetry={data.reload} /></div> :
      !data.data?.list.length ? <EmptyNote message="还没有分类，先创建一个来组织能力。" /> :
        <div className="data-table-wrap"><table className="data-table"><thead><tr><th>分类名称</th><th>分类编码</th><th>排序</th><th>状态</th><th>更新时间</th><th>操作</th></tr></thead><tbody>
          {data.data.list.map((item) => <tr key={item.id}><td><strong>{item.name}</strong></td><td><code className="mono">{item.code}</code></td><td>{item.sort}</td><td><StatusTag value={item.status} /></td><td className="record-time">{item.update_time}</td>
            <td><div className="row-actions"><button className="icon-button" aria-label={'编辑分类' + item.name} onClick={() => setEditing(item)}><Pencil size={14} /></button><button className="icon-button danger-icon" aria-label={'删除分类' + item.name} onClick={() => remove(item)}><Trash2 size={14} /></button></div></td></tr>)}
        </tbody></table></div>}
    {(creating || editing) && <CategoryEditor item={editing} onClose={() => { setCreating(false); setEditing(null) }} onSaved={updated} />}
  </section>
}
