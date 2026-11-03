import type { ModelProvider } from '@/api/provider'
import { FieldError, FormSection } from './editorUi'
import type { CapabilityFormState, FieldErrors } from './capabilityFormModel'
import {
  EXECUTOR_OPTIONS,
  executorProtocols,
  requiresProvider,
  type ExecutorCatalogView,
} from './executorResolver'

/**
 * P8：执行配置分组（执行器 / 供应商 / 输出上限）。
 * 供应商列表仅管理员可读（`/api/chat/providers` 对普通用户返回 2007），
 * 读不到时降级为只读文本，保存仍以后端校验为准。
 */
export function ExecutionFields({ form, errors, update, catalog, providers, providerNotice }: {
  form: CapabilityFormState
  errors: FieldErrors
  update: (patch: Partial<CapabilityFormState>) => void
  catalog?: ExecutorCatalogView | null
  /** 管理员可见的完整供应商列表；null 表示无权限或还没加载。 */
  providers: ModelProvider[] | null
  providerNotice?: string
}) {
  const enabled = (providers ?? []).filter((item) => item.status === 'enabled')
  const known = enabled.some((item) => item.alias === form.provider_alias)
  const protocols = form.executor ? executorProtocols(catalog, form.executor) : []
  return <FormSection title="执行配置" description="决定该能力由哪个执行器执行、走哪个上游供应商。">
    <div className="editor-row">
      <div className="field">
        <label className="field-label" htmlFor="cap-executor">执行器 *</label>
        <select id="cap-executor" className="form-control" value={form.executor}
          onChange={(e) => update({ executor: e.target.value })}>
          <option value="">请选择执行器</option>
          {EXECUTOR_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
        </select>
        <FieldError message={errors.executor} />
        {protocols.length > 0 && <p className="field-hint">
          只能绑定 {protocols.join(' / ')} 协议的供应商{requiresProvider(form.executor) ? '，且必须绑定一家' : '；留空表示使用全局默认供应商'}。
        </p>}
      </div>
      <div className="field">
        <label className="field-label" htmlFor="cap-provider">供应商</label>
        {providers
          ? <>
            <select id="cap-provider" className="form-control" value={form.provider_alias}
              onChange={(e) => update({ provider_alias: e.target.value })}>
              <option value="">全局默认（不绑定供应商）</option>
              {enabled.map((item) => <option key={item.id} value={item.alias}>{item.alias} · {item.protocol}</option>)}
              {form.provider_alias && !known && <option value={form.provider_alias}>{form.provider_alias}（当前绑定，未启用或不存在）</option>}
            </select>
            <p className="field-hint">只列出已启用的供应商；换绑立即影响该能力的所有调用方。</p>
          </>
          : <>
            <input id="cap-provider" className="form-control" value={form.provider_alias || '全局默认'} readOnly />
            <p className="field-hint">{providerNotice ?? '无法读取供应商列表（需要管理员权限），保存时以后端校验为准。'}</p>
          </>}
        <FieldError message={errors.provider} />
      </div>
    </div>
    <div className="editor-row">
      <div className="field">
        <label className="field-label" htmlFor="cap-max-tokens">输出 token 上限</label>
        <input id="cap-max-tokens" className="form-control" type="number" min={1} max={32768} step={1}
          value={form.max_output_tokens} onChange={(e) => update({ max_output_tokens: e.target.value })} />
        <FieldError message={errors.max_output_tokens} />
        <p className="field-hint">用于 chat / summary 的 max_tokens；文生图执行器忽略此项。</p>
      </div>
    </div>
  </FormSection>
}
