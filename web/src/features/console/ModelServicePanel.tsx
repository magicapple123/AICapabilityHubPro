import { App } from 'antd'
import { useCallback, useState } from 'react'
import { CheckCircle2, Cpu, Globe, XCircle } from 'lucide-react'
import { fetchManageCapabilities, updateCapability, type CapabilityManageItem } from '@/api/capability'
import { fetchProviders, setProviderStatus, testProvider, type ModelProvider } from '@/api/provider'
import { ProviderEditor } from '@/features/console/ProviderEditor'
import { EmptyNote, ErrorNote, Loading } from '@/components/ui'
import { useAsyncResource } from '@/hooks/useAsyncResource'
import { formatNumber } from '@/lib/dateRange'
import './provider-impact.css'

const BILLING_LABEL: Record<string, string> = {
  per_call: '按次',
  per_token: '按 token',
  per_unit: '按件',
}

function priceText(item: CapabilityManageItem): string {
  const mode = item.billing_mode ?? 'per_call'
  if (mode === 'per_token') {
    return `${formatNumber(item.price_per_1k_input ?? 0)} / ${formatNumber(item.price_per_1k_output ?? 0)} 积分 / 1k token`
  }
  if (mode === 'per_unit') {
    return `${formatNumber(item.price_per_unit ?? 0)} 积分 / ${item.unit || '件'}`
  }
  return `${formatNumber(item.price_per_call)} 积分 / 次`
}

/**
 * 模型服务视图（E4）：把「供应商 → 执行器 → 能力」摆在一屏里。
 * 只读为主，唯一的写操作是"市场展示"开关（与上下架相互独立）。
 */
export function ModelServicePanel() {
  // hooks 必须在任何 early return 之前调用，否则违反 rules-of-hooks
  const [editing, setEditing] = useState<ModelProvider | null>(null)
  const [editorOpen, setEditorOpen] = useState(false)
  const [aliasDrafts, setAliasDrafts] = useState<Record<number, string>>({})
  const { message, modal } = App.useApp()

  const load = useCallback(
    async () => {
      const [capabilities, providers] = await Promise.all([
        fetchManageCapabilities({ page_size: 100 }),
        fetchProviders(),
      ])
      return { capabilities: capabilities.list, providers: providers.list }
    },
    [],
  )
  const resource = useAsyncResource(load)

  if (resource.loading && !resource.data) return <div className="panel"><Loading label="正在读取模型服务…" /></div>
  if (resource.error) return <ErrorNote message={resource.error} onRetry={resource.reload} />
  if (!resource.data) return null

  const { capabilities, providers } = resource.data
  const providerByAlias = new Map(providers.map((item) => [item.alias, item]))
  // P3-b：影响面由能力列表聚合（能力归属在 capability_db，ai-chat 不持有）。
  // 停用/换钥前必须能看到"会让哪些能力同时不可用"，而不是停完才发现。
  const refsByAlias = new Map<string, CapabilityManageItem[]>()
  for (const item of capabilities) {
    if (!item.provider_alias) continue
    const bucket = refsByAlias.get(item.provider_alias) ?? []
    bucket.push(item)
    refsByAlias.set(item.provider_alias, bucket)
  }
  const impactOf = (alias: string) => refsByAlias.get(alias) ?? []
  const impactText = (alias: string) => {
    const refs = impactOf(alias)
    if (!refs.length) return '未被任何能力引用'
    const online = refs.filter((item) => item.status === 'online').length
    const market = refs.filter((item) => item.exposed_to_market !== false).length
    return `被 ${refs.length} 个能力引用（已上架 ${online} · 市场展示 ${market}）`
  }
  const confirmStatus = (provider: ModelProvider) => {
    const refs = impactOf(provider.alias)
    const next = provider.status === 'enabled' ? 'disabled' : 'enabled'
    if (next === 'enabled') {
      void setProviderStatus(provider.id, 'enabled')
        .then(() => { void message.success(`已启用 ${provider.alias}`); resource.reload() })
        .catch((cause: unknown) => {
          void message.error(cause instanceof Error ? cause.message : '启用失败')
        })
      return
    }
    modal.confirm({
      title: `停用供应商 ${provider.alias}？`,
      width: 520,
      okText: '确认停用', cancelText: '取消', okButtonProps: { danger: true },
      content: (
        <div>
          <p>停用后，绑定该供应商的能力会立刻返回 <code>2009 供应商不可用</code>，直到重新启用。</p>
          {refs.length ? (
            <ul className="provider-impact">
              {refs.map((item) => (
                <li key={item.id}>
                  <strong>{item.name}</strong>
                  <span className="muted"> #{item.id} · {item.status}
                    {item.exposed_to_market === false ? ' · 未展示' : ' · 市场展示中'}</span>
                </li>
              ))}
            </ul>
          ) : <p className="muted">当前没有能力绑定这个供应商，停用不会影响调用。</p>}
        </div>
      ),
      onOk: async () => {
        await setProviderStatus(provider.id, 'disabled')
        void message.success(`已停用 ${provider.alias}`)
        resource.reload()
      },
    })
  }

  const toggle = async (item: CapabilityManageItem, next: boolean) => {
    await updateCapability(item.id, { exposed_to_market: next })
    resource.reload()
  }

  const saveAlias = async (item: CapabilityManageItem) => {
    const alias = (aliasDrafts[item.id] ?? item.openai_alias ?? '').trim()
    try {
      await updateCapability(item.id, { openai_alias: alias || null })
      setAliasDrafts((current) => {
        const next = { ...current }
        delete next[item.id]
        return next
      })
      void message.success('对外模型名已更新')
      resource.reload()
    } catch (cause) {
      void message.error(cause instanceof Error ? cause.message : '对外模型名保存失败')
    }
  }

  return (
    <>
      <div className="panel">
        <div className="panel-head">
          <h2><Cpu size={16} /> 模型服务</h2>
          <span className="muted text-xs">供应商 {providers.length} 个 · 能力 {capabilities.length} 个</span>
        </div>
        <p className="muted text-xs" style={{ padding: '0 16px 8px' }}>
          执行器决定"怎么跑"，供应商标明"跑在哪"，市场展示决定"是否被看见"。上下架与展示是两个独立开关。
        </p>
        {!capabilities.length ? <EmptyNote message="还没有登记能力。" /> : (
          <div className="data-table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>能力 / 编码</th>
                  <th>执行器</th>
                  <th>供应商</th>
                  <th>计价</th>
                  <th>输出上限</th>
                  <th>市场展示</th>
                </tr>
              </thead>
              <tbody>
                {capabilities.map((item) => {
                  const provider = item.provider_alias ? providerByAlias.get(item.provider_alias) : undefined
                  return (
                    <tr key={item.id}>
                      <td>
                        <strong>{item.name}</strong>
                        <small className="muted"> {item.code}</small>
                        <div style={{ display: 'flex', gap: 6, marginTop: 6, maxWidth: 260 }}>
                          <input
                            className="form-control mono text-xs"
                            aria-label={`对外模型名 ${item.name}`}
                            maxLength={64}
                            pattern="[a-z][a-z0-9._-]{1,63}"
                            placeholder="对外模型名（可选）"
                            value={aliasDrafts[item.id] ?? item.openai_alias ?? ''}
                            onChange={(event) => setAliasDrafts((current) => ({
                              ...current, [item.id]: event.target.value,
                            }))}
                          />
                          <button
                            className="text-button"
                            type="button"
                            aria-label={`保存对外模型名 ${item.name}`}
                            disabled={(aliasDrafts[item.id] ?? item.openai_alias ?? '').trim() === (item.openai_alias ?? '')}
                            onClick={() => { void saveAlias(item) }}
                          >保存</button>
                        </div>
                      </td>
                      <td className="mono text-xs">{item.executor || '—'}</td>
                      <td>
                        {item.provider_alias
                          ? <><span className="mono text-xs">{item.provider_alias}</span>
                            <small className="muted"> {provider ? provider.status : '未登记'}</small></>
                          : <span className="muted">全局默认</span>}
                      </td>
                      <td>{BILLING_LABEL[item.billing_mode ?? 'per_call']} · {priceText(item)}</td>
                      <td className="mono text-xs">{formatNumber(item.max_output_tokens ?? 1024)}</td>
                      <td>
                        <label className="switch-inline">
                          <input
                            type="checkbox"
                            checked={item.exposed_to_market !== false}
                            onChange={(event) => toggle(item, event.target.checked)}
                          />
                          {item.exposed_to_market === false
                            ? <><XCircle size={13} /> 已隐藏</>
                            : <><CheckCircle2 size={13} /> 展示中</>}
                        </label>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="panel" style={{ marginTop: 16 }}>
        <div className="panel-head">
          <h2><Globe size={16} /> 上游供应商</h2>
          <button
            className="text-button"
            onClick={() => { setEditing(null); setEditorOpen(true) }}
          >
            新增供应商
          </button>
        </div>
        {!providers.length ? <EmptyNote message="还没有登记供应商；可先用全局模型配置。" /> : (
          <div className="data-table-wrap">
            <table className="data-table">
              <thead>
                <tr><th>名称 / 别名</th><th>协议</th><th>地址</th><th>密钥</th><th>状态</th><th>影响面</th><th>连通性</th><th>操作</th></tr>
              </thead>
              <tbody>
                {providers.map((provider: ModelProvider) => (
                  <tr key={provider.id}>
                    <td><strong>{provider.name}</strong><small className="muted"> {provider.alias}</small></td>
                    <td className="mono text-xs">{provider.protocol}</td>
                    <td className="mono text-xs">{provider.base_url}</td>
                    <td className="mono text-xs">{provider.api_key_mask || '—'}</td>
                    <td>
                      {provider.status}
                      {/* 换钥会把供应商退回 draft：此时绑定它的能力已经全部不可用，
                          必须在列表上直接说出来，而不是只显示一个 "draft"。 */}
                      {provider.status === 'draft' && impactOf(provider.alias).length > 0
                        ? <div className="provider-draft-hint">待重测，影响 {impactOf(provider.alias).length} 个能力</div>
                        : null}
                    </td>
                    <td className="text-xs">{impactText(provider.alias)}</td>
                    <td>
                      <button
                        className="text-button"
                        onClick={async () => {
                          try {
                            const result = await testProvider(provider.id)
                            if (result.ok) void message.success(`连通正常（${result.elapsed_ms}ms）`)
                            else void message.error(`不可用：${result.reason}`)
                          } catch (cause) {
                            void message.error(cause instanceof Error ? cause.message : '测试失败')
                          }
                          resource.reload()
                        }}
                      >
                        测试
                      </button>
                    </td>
                    <td className="admin-actions">
                      <button className="text-button" onClick={() => { setEditing(provider); setEditorOpen(true) }}>
                        编辑
                      </button>
                      <button
                        className="text-button"
                        onClick={() => confirmStatus(provider)}
                      >
                        {provider.status === 'enabled' ? '停用' : '启用'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      {editorOpen ? (
        <ProviderEditor
          provider={editing}
          onClose={() => setEditorOpen(false)}
          onSaved={resource.reload}
        />
      ) : null}
    </>
  )
}
