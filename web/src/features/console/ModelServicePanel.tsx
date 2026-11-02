import { useCallback } from 'react'
import { CheckCircle2, Cpu, Globe, XCircle } from 'lucide-react'
import { fetchManageCapabilities, updateCapability, type CapabilityManageItem } from '@/api/capability'
import { fetchProviders, testProvider, type ModelProvider } from '@/api/provider'
import { EmptyNote, ErrorNote, Loading } from '@/components/ui'
import { useAsyncResource } from '@/hooks/useAsyncResource'
import { formatNumber } from '@/lib/dateRange'

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

  const toggle = async (item: CapabilityManageItem, next: boolean) => {
    await updateCapability(item.id, { exposed_to_market: next })
    resource.reload()
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
          <span className="muted text-xs">密钥只显示掩码，明文不出服务端</span>
        </div>
        {!providers.length ? <EmptyNote message="还没有登记供应商；可先用全局模型配置。" /> : (
          <div className="data-table-wrap">
            <table className="data-table">
              <thead>
                <tr><th>名称 / 别名</th><th>协议</th><th>地址</th><th>密钥</th><th>状态</th><th>连通性</th></tr>
              </thead>
              <tbody>
                {providers.map((provider: ModelProvider) => (
                  <tr key={provider.id}>
                    <td><strong>{provider.name}</strong><small className="muted"> {provider.alias}</small></td>
                    <td className="mono text-xs">{provider.protocol}</td>
                    <td className="mono text-xs">{provider.base_url}</td>
                    <td className="mono text-xs">{provider.api_key_mask || '—'}</td>
                    <td>{provider.status}</td>
                    <td>
                      <button
                        className="text-button"
                        onClick={async () => {
                          const result = await testProvider(provider.id)
                          window.alert(result.ok ? '连通正常' : `不可用：${result.reason}`)
                          resource.reload()
                        }}
                      >
                        测试
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  )
}
