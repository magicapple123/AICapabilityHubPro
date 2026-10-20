import { App } from 'antd'
import { useRef, useState } from 'react'
import { createCapability, updateCapability, type CapabilityManageItem, type CategoryItem, type CapabilityCreatePayload } from '@/api/capability'
import { ErrorNote, Modal } from '@/components/ui'

export function CapabilityEditor({ item, categories, onClose, onSaved }: {
  item: CapabilityManageItem | null; categories: CategoryItem[]; onClose: () => void; onSaved: () => void
}) {
  const [form, setForm] = useState({
    name: item?.name ?? '', code: item?.code ?? '', category_id: String(item?.category_id ?? ''),
    service_name: item?.service_name ?? '', path: item?.path ?? '', price: String(item?.price_per_call ?? 0),
    description: item?.description ?? '', schema: item?.param_schema ? JSON.stringify(item.param_schema, null, 2) : '', status: 'draft',
  })
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const locked = useRef(false)
  const { message } = App.useApp()
  const update = (name: keyof typeof form, value: string) => setForm((old) => ({ ...old, [name]: value }))
  const submit = async () => {
    if (locked.current) return
    let schema: Record<string, unknown> | null = null
    try {
      if (form.schema.trim()) {
        const parsed: unknown = JSON.parse(form.schema)
        if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) throw new Error('Schema 必须是 JSON 对象')
        schema = parsed as Record<string, unknown>
      }
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Schema 格式无效'); return }
    if (!form.name.trim() || !/^[a-z0-9][a-z0-9-]*$/.test(form.code) || !Number(form.category_id) || !form.service_name.trim() || !form.path.startsWith('/') ||
      !Number.isInteger(Number(form.price)) || Number(form.price) < 0) { setError('请检查必填字段，价格需为非负整数，调用路径需以 / 开头。'); return }
    locked.current = true; setSaving(true); setError('')
    try {
      const payload: CapabilityCreatePayload = {
        name: form.name.trim(), code: form.code.trim(), category_id: Number(form.category_id),
        service_name: form.service_name.trim(), path: form.path.trim(), price_per_call: Number(form.price),
        description: form.description.trim(), param_schema: schema,
      }
      if (item) await updateCapability(item.id, payload)
      else await createCapability({ ...payload, status: form.status as 'draft' | 'online' | 'offline' })
      void message.success(item ? '能力已更新' : '能力已登记')
      onSaved()
    } catch (cause) { setError(cause instanceof Error ? cause.message : '保存失败') }
    finally { locked.current = false; setSaving(false) }
  }
  return <Modal title={item ? '编辑能力' : '登记新能力'} open onClose={() => { if (!saving) onClose() }}>
    <form className="editor-form" onSubmit={(e) => { e.preventDefault(); void submit() }}><fieldset disabled={saving} className="editor-fieldset">
      <div className="editor-row"><label className="field"><span className="field-label">能力名称 *</span><input className="form-control" required maxLength={64} value={form.name} onChange={(e) => update('name', e.target.value)} /></label>
        <label className="field"><span className="field-label">能力编码 *</span><input className="form-control" required pattern="[a-z0-9][a-z0-9-]*" value={form.code} onChange={(e) => update('code', e.target.value)} /></label></div>
      <div className="editor-row"><label className="field"><span className="field-label">所属分类 *</span><select className="form-control" required value={form.category_id} onChange={(e) => update('category_id', e.target.value)}><option value="">请选择分类</option>{categories.map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}</select></label>
        <label className="field"><span className="field-label">每次调用积分 *</span><input className="form-control" type="number" step="1" min="0" required value={form.price} onChange={(e) => update('price', e.target.value)} /></label></div>
      <details className="editor-advanced" open><summary>服务登记信息</summary><div className="editor-row"><label className="field"><span className="field-label">服务名 *</span><input className="form-control" required value={form.service_name} onChange={(e) => update('service_name', e.target.value)} /></label><label className="field"><span className="field-label">调用路径 *</span><input className="form-control" required pattern="/.*" value={form.path} onChange={(e) => update('path', e.target.value)} /></label></div><p className="field-hint">登记信息不会开启任意转发，实际执行由已接入的受控执行器决定。</p></details>
      <label className="field"><span className="field-label">能力描述</span><textarea className="form-control" rows={3} value={form.description} onChange={(e) => update('description', e.target.value)} /></label>
      <label className="field"><span className="field-label">输入 Schema（JSON 对象）</span><textarea className="form-control mono" rows={6} spellCheck={false} value={form.schema} onChange={(e) => update('schema', e.target.value)} placeholder={'{"type":"object","properties":{}}'} /></label>
      {!item && <label className="field"><span className="field-label">初始状态</span><select className="form-control" value={form.status} onChange={(e) => update('status', e.target.value)}><option value="draft">草稿</option><option value="online">已上架</option><option value="offline">已下架</option></select></label>}
      {error && <ErrorNote message={error} />}<div className="form-actions"><button className="button-secondary" type="button" onClick={onClose} disabled={saving}>取消</button><button type="submit" className="button-primary" disabled={saving}>{saving ? '保存中…' : '保存能力'}</button></div>
    </fieldset></form>
  </Modal>
}
