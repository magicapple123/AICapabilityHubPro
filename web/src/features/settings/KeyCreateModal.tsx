import { useRef, useState } from 'react'
import { createApiKey, type ApiKeyCreated } from '@/api/user'
import { ErrorNote, Modal } from '@/components/ui'

export function KeyCreateModal({ onClose, onCreated }: { onClose: () => void; onCreated: (key: ApiKeyCreated) => void }) {
  const [name, setName] = useState('')
  const [expires, setExpires] = useState('')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const locked = useRef(false)
  const submit = async () => {
    if (locked.current) return
    if (expires && (!Number.isFinite(new Date(expires).getTime()) || new Date(expires) <= new Date())) {
      setError('请选择未来的有效期时间，或留空表示长期有效。'); return
    }
    setError(''); locked.current = true; setSaving(true)
    try {
      const key = await createApiKey({ name: name.trim() || undefined, expire_time: expires ? expires.replace('T', ' ') + (expires.length === 16 ? ':00' : '') : undefined })
      onCreated(key)
    } catch (cause) { setError(cause instanceof Error ? cause.message : '创建失败，请稍后重试') }
    finally { locked.current = false; setSaving(false) }
  }
  return <Modal open title="创建 API Key" onClose={() => { if (!saving) onClose() }}>
    <form className="key-create-form" onSubmit={(event) => { event.preventDefault(); void submit() }}>
      <label className="field"><span className="field-label">名称 <span className="muted">（可选）</span></span><input autoFocus className="form-control" maxLength={32} value={name} disabled={saving} onChange={(e) => setName(e.target.value)} placeholder="例如：本地开发、课程演示" /><span className="field-hint">使用容易辨认的名称，方便日后管理。</span></label>
      <label className="field"><span className="field-label">有效期（Asia/Shanghai） <span className="muted">（可选）</span></span><input className="form-control" type="datetime-local" value={expires} disabled={saving} onChange={(e) => setExpires(e.target.value)} /><span className="field-hint">按北京时间设置，留空表示长期有效。</span></label>
      {error && <ErrorNote message={error} />}
      <p className="inline-note">创建后请立即保存 Secret Key，之后平台仅展示密钥掩码。</p>
      <div className="form-actions"><button type="button" className="button-secondary" onClick={onClose} disabled={saving}>取消</button><button type="submit" className="button-primary" disabled={saving}>{saving ? '创建中…' : '创建 API Key'}</button></div>
    </form>
  </Modal>
}
