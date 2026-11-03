import { App } from 'antd'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  createCapability, updateCapability,
  type CapabilityManageItem, type CapabilityStatus, type CategoryItem,
} from '@/api/capability'
import { fetchProviders, type ModelProvider } from '@/api/provider'
import { ErrorNote } from '@/components/ui'
import { useAsyncResource } from '@/hooks/useAsyncResource'
import { useAuthStore } from '@/stores/auth'
import { ExecutionFields } from '@/features/capabilities/ExecutionFields'
import { PricingFields } from '@/features/capabilities/PricingFields'
import { SchemaFields } from '@/features/capabilities/SchemaFields'
import { EditorModal, FieldError, FormSection } from '@/features/capabilities/editorUi'
import {
  buildPayload, checkSchemaText, executorHint, fieldKeyOf, initialForm, summarizeErrors,
  validateCapabilityForm,
  type CapabilityFormState, type FieldErrors, type ProviderOption,
} from '@/features/capabilities/capabilityFormModel'
import {
  isExecutorSupported, supportedExecutors, type ExecutorCatalogView,
} from '@/features/capabilities/executorResolver'
import '@/styles/capability-editor.css'

const HINT_CLASS = { idle: 'field-hint', ready: 'field-hint cap-hint-ready', warn: 'field-hint cap-hint-warn' }

/** P8/P9：能力登记与编辑表单（执行配置 / 计价 / 展示 / 基本 / Schema）。 */
export function CapabilityEditor({ item, categories, executorCatalog, onClose, onSaved }: {
  item: CapabilityManageItem | null
  categories: CategoryItem[]
  /** `/api/chat/executors` 目录；undefined/null 表示还没拿到，不做"未接入"断言。 */
  executorCatalog?: ExecutorCatalogView | null
  onClose: () => void
  onSaved: () => void
}) {
  const [form, setForm] = useState<CapabilityFormState>(() => initialForm(item))
  const [errors, setErrors] = useState<FieldErrors>({})
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const locked = useRef(false)
  const { message } = App.useApp()

  // 供应商列表仅管理员可读（/api/chat/providers 对普通用户 2007），角色已知时先不请求。
  const role = useAuthStore((state) => state.role)
  const canReadProviders = role === '' || role === 'admin'
  const loadProviders = useCallback(
    () => (canReadProviders ? fetchProviders() : Promise.resolve({ list: [] as ModelProvider[], total: 0 })),
    [canReadProviders],
  )
  const providers = useAsyncResource(loadProviders)
  const providerList: ModelProvider[] | null = canReadProviders && providers.data ? providers.data.list : null
  const providerOptions: ProviderOption[] | null = providerList && providerList.length > 0
    ? providerList.map((one) => ({ alias: one.alias, protocol: one.protocol, status: one.status }))
    : null
  const providerNotice = !canReadProviders
    ? '当前账号无法读取供应商列表，保存时以后端校验为准（2007）。'
    : providers.error ? '读取供应商列表失败：' + providers.error : '正在读取供应商列表…'

  const supported = supportedExecutors(executorCatalog)
  const executorReady = isExecutorSupported(executorCatalog, form.executor)
  const hint = executorHint(form, supported)

  const update = (patch: Partial<CapabilityFormState>) => {
    setForm((old) => ({ ...old, ...patch }))
    setErrors((old) => {
      const next = { ...old }
      for (const key of Object.keys(patch) as Array<keyof CapabilityFormState>) delete next[fieldKeyOf(key)]
      return next
    })
  }

  // P9.6：执行器未接入时不允许直接把初始状态选成「已上架」。
  useEffect(() => {
    if (form.status !== 'online' || executorReady) return
    setForm((old) => (old.status === 'online' ? { ...old, status: 'draft' } : old))
  }, [executorReady, form.status])

  const validateSchema = () => {
    const problem = checkSchemaText(form.schema)
    setErrors((old) => {
      const next = { ...old }
      if (problem) next.schema = problem
      else delete next.schema
      return next
    })
  }

  const submit = async () => {
    if (locked.current) return
    const result = validateCapabilityForm({ form, catalog: executorCatalog, supported, providers: providerOptions })
    setErrors(result.errors)
    if (Object.keys(result.errors).length > 0) { setError(summarizeErrors(result.errors)); return }
    setError('')
    locked.current = true; setSaving(true)
    try {
      const payload = buildPayload(form, result.schema)
      if (item) await updateCapability(item.id, payload)
      else await createCapability({ ...payload, status: form.status })
      void message.success(item ? '能力已更新' : '能力已登记')
      onSaved()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '保存失败')
    } finally {
      locked.current = false; setSaving(false)
    }
  }

  return <EditorModal title={item ? '编辑能力' : '登记新能力'} onClose={() => { if (!saving) onClose() }}>
    <form className="editor-form cap-editor" onSubmit={(e) => { e.preventDefault(); void submit() }}>
      <fieldset disabled={saving} className="editor-fieldset">
        <FormSection title="基本信息">
          <div className="editor-row">
            <div className="field">
              <label className="field-label" htmlFor="cap-name">能力名称 *</label>
              <input id="cap-name" className="form-control" maxLength={64} value={form.name}
                onChange={(e) => update({ name: e.target.value })} />
              <FieldError message={errors.name} />
            </div>
            <div className="field">
              <label className="field-label" htmlFor="cap-code">能力编码 *</label>
              <input id="cap-code" className="form-control" maxLength={64} value={form.code}
                onChange={(e) => update({ code: e.target.value })} />
              <FieldError message={errors.code} />
              {hint.text && <p className={HINT_CLASS[hint.tone]}>{hint.text}</p>}
            </div>
          </div>
          <div className="editor-row">
            <div className="field">
              <label className="field-label" htmlFor="cap-category">所属分类 *</label>
              <select id="cap-category" className="form-control" value={form.category_id}
                onChange={(e) => update({ category_id: e.target.value })}>
                <option value="">请选择分类</option>
                {categories.map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}
              </select>
              <FieldError message={errors.category} />
              {categories.length === 0 && <p className="field-hint">
                还没有分类，<Link className="text-link" to="/console?tab=categories">去创建分类</Link>后回来登记。
              </p>}
            </div>
            <div className="field">
              <label className="field-label" htmlFor="cap-alias">对外模型名（可选）</label>
              <input id="cap-alias" className="form-control" maxLength={64} value={form.openai_alias}
                onChange={(e) => update({ openai_alias: e.target.value })} />
              <FieldError message={errors.openai_alias} />
              <p className="field-hint">用于 `/v1/models` 与 OpenAI 兼容接口；留空则不发布模型别名。</p>
            </div>
          </div>
          <div className="field">
            <label className="field-label" htmlFor="cap-description">能力描述</label>
            <textarea id="cap-description" className="form-control" rows={3} maxLength={512}
              value={form.description} onChange={(e) => update({ description: e.target.value })} />
          </div>
        </FormSection>

        <ExecutionFields form={form} errors={errors} update={update} catalog={executorCatalog}
          providers={providerList} providerNotice={providerNotice} />

        <PricingFields form={form} errors={errors} update={update} />

        <FormSection title="展示">
          <label className="cap-switch">
            <input type="checkbox" checked={form.exposed_to_market}
              onChange={(e) => update({ exposed_to_market: e.target.checked })} />
            <span>在市场展示该能力</span>
          </label>
          <p className="field-hint">关闭后能力仍在目录中（可继续调试），但不出现在能力市场。与上架状态相互独立。</p>
        </FormSection>

        <SchemaFields value={form.schema} error={errors.schema}
          onChange={(value) => update({ schema: value })} onValidate={validateSchema} />

        <details className="editor-advanced">
          <summary>高级 / 兼容字段（服务名与调用路径）</summary>
          <p className="field-hint">已预填后端惯用值，通常无需修改；登记信息不会开启任意转发，实际执行由所选执行器决定。</p>
          <div className="editor-row">
            <div className="field">
              <label className="field-label" htmlFor="cap-service">服务名</label>
              <input id="cap-service" className="form-control" maxLength={64} value={form.service_name}
                onChange={(e) => update({ service_name: e.target.value })} />
              <FieldError message={errors.service} />
            </div>
            <div className="field">
              <label className="field-label" htmlFor="cap-path">调用路径</label>
              <input id="cap-path" className="form-control" maxLength={255} value={form.path}
                onChange={(e) => update({ path: e.target.value })} />
              <FieldError message={errors.path} />
            </div>
          </div>
        </details>

        {!item && <FormSection title="发布设置">
          <div className="field">
            <label className="field-label" htmlFor="cap-status">初始状态</label>
            <select id="cap-status" className="form-control" value={form.status}
              onChange={(e) => update({ status: e.target.value as CapabilityStatus })}>
              <option value="draft">草稿</option>
              <option value="online" disabled={!executorReady}>
                {executorReady ? '已上架' : '已上架（需先选择并接入执行器）'}
              </option>
              <option value="offline">已下架</option>
            </select>
            {!executorReady && <p className="field-hint cap-hint-warn">执行器未选择或尚未接入，暂不能直接上架；后端仍会做最终校验。</p>}
          </div>
        </FormSection>}

        {error && <ErrorNote message={error} />}
        <div className="form-actions">
          <button className="button-secondary" type="button" onClick={onClose} disabled={saving}>取消</button>
          <button type="submit" className="button-primary" disabled={saving}>{saving ? '保存中…' : '保存能力'}</button>
        </div>
      </fieldset>
    </form>
  </EditorModal>
}
