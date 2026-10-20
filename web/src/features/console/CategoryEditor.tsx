import { App } from 'antd'
import { useRef, useState } from 'react'
import { createCategory, updateCategory, type CategoryItem, type CategoryStatus } from '@/api/capability'
import { ErrorNote, Modal } from '@/components/ui'

export function CategoryEditor({ item, onClose, onSaved }: { item: CategoryItem | null; onClose: () => void; onSaved: () => void }) {
  const [name, setName] = useState(item?.name ?? '')
  const [code, setCode] = useState(item?.code ?? '')
  const [sort, setSort] = useState(String(item?.sort ?? 0))
  const [status, setStatus] = useState<CategoryStatus>(item?.status ?? 'enabled')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const locked = useRef(false)
  const { message } = App.useApp()
  const submit = async () => {
    if (locked.current) return
    if (!name.trim() || !/^[a-z0-9][a-z0-9-]*$/.test(code.trim()) || !Number.isInteger(Number(sort))) { setError('请填写名称、有效编码和整数排序值。'); return }
    locked.current = true; setSaving(true); setError('')
    try {
      const payload = { name: name.trim(), code: code.trim(), sort: Number(sort) }
      if (item) await updateCategory(item.id, { ...payload, status }); else await createCategory(payload)
      void message.success(item ? '分类已更新' : '分类已创建')
      onSaved()
    } catch (cause) { setError(cause instanceof Error ? cause.message : '保存失败') }
    finally { locked.current = false; setSaving(false) }
  }
  return <Modal title={item ? '编辑分类' : '新增分类'} open onClose={() => { if (!saving) onClose() }}>
    <form className="editor-form" onSubmit={(e) => { e.preventDefault(); void submit() }}>
      <label className="field"><span className="field-label">分类名称</span><input className="form-control" required maxLength={64} value={name} disabled={saving} onChange={(e) => setName(e.target.value)} /></label>
      <label className="field"><span className="field-label">分类编码</span><input className="form-control" required pattern="[a-z0-9][a-z0-9-]*" value={code} disabled={saving} onChange={(e) => setCode(e.target.value)} /><span className="field-hint">小写字母、数字与连字符</span></label>
      <div className="editor-row"><label className="field"><span className="field-label">排序值</span><input className="form-control" type="number" step="1" required value={sort} disabled={saving} onChange={(e) => setSort(e.target.value)} /></label>
        {item && <label className="field"><span className="field-label">状态</span><select className="form-control" value={status} disabled={saving} onChange={(e) => setStatus(e.target.value as CategoryStatus)}><option value="enabled">启用</option><option value="disabled">停用</option></select></label>}</div>
      {error && <ErrorNote message={error} />}<div className="form-actions"><button className="button-secondary" type="button" onClick={onClose} disabled={saving}>取消</button><button type="submit" className="button-primary" disabled={saving}>{saving ? '保存中…' : '保存分类'}</button></div>
    </form>
  </Modal>
}
