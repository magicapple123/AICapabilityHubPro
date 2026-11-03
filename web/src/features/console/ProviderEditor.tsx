import { useEffect, useState } from 'react'
import { X } from 'lucide-react'
import {
  createProvider, updateProvider, type ModelProvider, type ProviderPayload,
  type ProviderUpdatePayload,
} from '@/api/provider'

const PROTOCOLS: { value: ProviderPayload['protocol']; label: string; hint: string }[] = [
  { value: 'openai-chat', label: 'openai-chat', hint: 'OpenAI 兼容的对话补全' },
  { value: 'openai-responses', label: 'openai-responses', hint: '只暴露 /responses 的上游' },
  { value: 'openai-image', label: 'openai-image', hint: '同步 /images/generations' },
  { value: 'dashscope-image', label: 'dashscope-image', hint: '百炼异步任务（提交+轮询）' },
  { value: 'openai-embedding', label: 'openai-embedding', hint: '向量化' },
  { value: 'custom-http', label: 'custom-http', hint: '自定义 HTTP' },
]

/** 表单内部状态：api_key 在表单里恒为字符串（编辑时留空表示不改）。 */
type FormState = Omit<ProviderPayload, 'api_key'> & { api_key: string }

const EMPTY: FormState = {
  name: '', alias: '', protocol: 'openai-chat', base_url: '',
  api_key: '', default_model: '', timeout_ms: 30000,
}

const ALIAS_PATTERN = /^[a-z][a-z0-9-]{1,63}$/

interface Props {
  /** 传入表示编辑；为空表示新增。 */
  provider: ModelProvider | null
  onClose: () => void
  onSaved: () => void
}

/**
 * 供应商新增/编辑表单。
 *
 * 两个刻意的设计：
 * - 编辑时 api_key 留空 = 不修改密钥（后端只回掩码，前端拿不到明文，不能回填）。
 * - 提交前做本地校验，但**唯一权威仍是后端**：SSRF 白名单、协议白名单都在服务端，
 *   这里只拦明显的格式错误，避免用户白等一次往返。
 */
export function ProviderEditor({ provider, onClose, onSaved }: Props) {
  const [form, setForm] = useState<FormState>(EMPTY)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  const isEdit = provider !== null

  useEffect(() => {
    if (provider) {
      setForm({
        name: provider.name, alias: provider.alias,
        protocol: provider.protocol as ProviderPayload['protocol'],
        base_url: provider.base_url, api_key: '',
        default_model: provider.default_model, timeout_ms: provider.timeout_ms,
      })
    } else {
      setForm(EMPTY)
    }
  }, [provider])

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }))

  /** 编辑态 alias / protocol 由服务端保持原值，前端只读展示。 */
  const lockedStyle = isEdit ? { opacity: 0.6, cursor: 'not-allowed' } : undefined

  const submit = async () => {
    setError('')
    if (!form.name.trim() || !form.base_url.trim()) {
      setError('名称、地址为必填项')
      return
    }
    // 别名只在创建时校验/提交：编辑态别名不可变，校验它只会造成误拦截。
    if (!provider) {
      if (!form.alias.trim()) {
        setError('别名不能为空')
        return
      }
      if (!ALIAS_PATTERN.test(form.alias)) {
        setError('别名需为小写字母开头、只含小写字母/数字/短横线，2-64 位')
        return
      }
      if (!form.api_key.trim()) {
        setError('新增时必须填写 API Key')
        return
      }
    }
    setSubmitting(true)
    try {
      if (provider) {
        // 后端 ProviderUpdateRequest 为 extra="forbid"，只接受下面这几个字段；
        // 显式构造而非展开 form，避免 alias / protocol 泄漏进去触发 422（code 2001）。
        const payload: ProviderUpdatePayload = {
          name: form.name,
          base_url: form.base_url,
          default_model: form.default_model,
          timeout_ms: form.timeout_ms,
        }
        // api_key 留空 = 不轮换，字段直接不出现在请求体里。
        if (form.api_key) payload.api_key = form.api_key
        await updateProvider(provider.id, payload)
      } else {
        await createProvider(form)
      }
      onSaved()
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存失败')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="modal-mask" role="dialog" aria-modal="true">
      <div className="modal-card">
        <div className="modal-head">
          <h3>{provider ? `编辑供应商 · ${provider.name}` : '新增上游供应商'}</h3>
          <button className="icon-button" onClick={onClose} aria-label="关闭"><X size={16} /></button>
        </div>

        <div className="modal-body">
          <label className="field">
            <span>名称</span>
            <input value={form.name} onChange={(e) => set('name', e.target.value)} placeholder="阿里云百炼" />
          </label>
          <label className="field">
            <span>别名（能力绑定用）</span>
            <input
              value={form.alias}
              onChange={(e) => set('alias', e.target.value)}
              placeholder="dashscope"
              disabled={isEdit}
              style={lockedStyle}
            />
            {isEdit
              ? <span className="field-hint">别名创建后不可修改，如需变更请新建供应商。</span>
              : null}
          </label>
          <label className="field">
            <span>协议</span>
            <select
              value={form.protocol}
              onChange={(e) => set('protocol', e.target.value as FormState['protocol'])}
              disabled={isEdit}
              style={lockedStyle}
            >
              {PROTOCOLS.map((item) => (
                <option key={item.value} value={item.value}>{item.label} — {item.hint}</option>
              ))}
            </select>
            {isEdit
              ? <span className="field-hint">协议创建后不可修改，如需变更请新建供应商。</span>
              : null}
          </label>
          <label className="field">
            <span>Base URL</span>
            <input
              value={form.base_url}
              onChange={(e) => set('base_url', e.target.value)}
              placeholder="https://dashscope.aliyuncs.com"
            />
          </label>
          <label className="field">
            <span>API Key {provider ? '（留空表示不修改）' : ''}</span>
            <input
              type="password"
              value={form.api_key}
              onChange={(e) => set('api_key', e.target.value)}
              placeholder={provider ? provider.api_key_mask : 'sk-...'}
              autoComplete="new-password"
            />
          </label>
          <label className="field">
            <span>默认模型</span>
            <input
              value={form.default_model}
              onChange={(e) => set('default_model', e.target.value)}
              placeholder="wanx2.1-t2i-turbo"
            />
            {!form.default_model.trim() && <span className="field-hint">未填默认模型时，每次平台 API 调用必须显式指定 model；/v1 使用平台别名，不能代填上游模型。</span>}
          </label>
          <label className="field">
            <span>超时（毫秒）</span>
            <input
              type="number" min={1000} max={120000} step={1000}
              value={form.timeout_ms}
              onChange={(e) => set('timeout_ms', Number(e.target.value) || 30000)}
            />
          </label>
          <p className="muted text-xs">
            密钥由服务端用主密钥加密后落库，接口只回掩码；地址会经过 SSRF 白名单校验。
          </p>
          {error ? <p className="form-error">{error}</p> : null}
        </div>

        <div className="modal-foot">
          <button className="text-button" onClick={onClose} disabled={submitting}>取消</button>
          <button className="primary-button" onClick={submit} disabled={submitting}>
            {submitting ? '保存中…' : '保存'}
          </button>
        </div>
      </div>
    </div>
  )
}
