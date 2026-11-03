import { App } from 'antd'
import { BookOpen, KeyRound, Plus, ShieldCheck } from 'lucide-react'
import { useState } from 'react'
import { disableApiKey, fetchApiKeys, type ApiKeyCreated, type ApiKeyItem } from '@/api/user'
import { CopyButton } from '@/components/CopyButton'
import { EmptyNote, ErrorNote, Loading, StatusTag } from '@/components/ui'
import { useAsyncResource } from '@/hooks/useAsyncResource'
import { ApiKeyUsageDrawer, type ApiKeyUsageTarget } from './ApiKeyUsageDrawer'
import { KeyCreateModal } from './KeyCreateModal'
import { KeySecretModal } from './KeySecretModal'

export function ApiKeySettings() {
  const keys = useAsyncResource(fetchApiKeys)
  const [creating, setCreating] = useState(false)
  const [created, setCreated] = useState<ApiKeyCreated | null>(null)
  const [disabling, setDisabling] = useState<number | null>(null)
  const [usage, setUsage] = useState<ApiKeyUsageTarget | null>(null)
  const { modal, message } = App.useApp()
  const disable = (key: ApiKeyItem) => modal.confirm({
    title: '禁用此 API Key？', content: '「' + (key.name || '未命名 Key') + '」禁用后将不能继续使用。此操作不会删除已有调用记录。',
    okText: '确认禁用', cancelText: '取消', okButtonProps: { danger: true },
    onOk: async () => {
      setDisabling(key.id)
      try { await disableApiKey(key.id); void message.success('API Key 已禁用'); keys.reload() }
      catch (cause) { void message.error(cause instanceof Error ? cause.message : '禁用失败'); throw cause }
      finally { setDisabling(null) }
    },
  })
  const openUsage = (key?: ApiKeyItem) =>
    setUsage({ accessKey: key?.access_key, keyName: key?.name })
  /** 创建成功后的入口：Secret 只在内存里传给抽屉，不写 localStorage、不进日志。 */
  const openCreatedUsage = (key: ApiKeyCreated) =>
    setUsage({ accessKey: key.access_key, keyName: key.name, secretKey: key.secret_key })
  return <>
    {/* P3-a：顶部只留一行摘要，完整两种用法由「使用方法」抽屉承载，避免两处文案互相矛盾。 */}
    <div className="key-notice"><ShieldCheck size={19} /><div><strong>妥善保管访问凭证</strong>
      <p>Secret Key 只在创建时展示一次，请立即保存。两套凭证不可互换：<code>sk_</code> 用于 OpenAI 兼容（<code>/v1</code>），exchange 换来的 JWT 用于平台接口（<code>/api</code>）。</p>
      <p><button className="text-link" onClick={() => openUsage()}><BookOpen size={13} />查看两种用法的完整 curl 与客户端配置</button></p>
    </div></div>
    <section className="panel"><div className="panel-head"><div><h2>API Key 管理</h2><p>为不同用途创建独立凭证，按需禁用</p></div>
      <div className="admin-actions">
        <button className="button-secondary" onClick={() => openUsage()}><BookOpen size={14} />使用方法</button>
        <button className="button-primary" onClick={() => setCreating(true)}><Plus size={15} />新建 API Key</button>
      </div></div>
      {keys.loading ? <Loading label="正在加载访问凭证…" /> : keys.error ? <div className="panel-body"><ErrorNote message={keys.error} onRetry={keys.reload} /></div> :
        !keys.data?.list.length ? <EmptyNote message="还没有访问凭证。创建一个 API Key，集中管理你的访问授权。"
          action={<button className="button-secondary" onClick={() => setCreating(true)}><KeyRound size={14} />创建第一个 API Key</button>} /> :
        <div className="data-table-wrap"><table className="data-table key-table"><thead><tr><th>名称 / Access Key</th><th>Secret Key</th><th>状态</th><th>有效期</th><th>操作</th></tr></thead>
          <tbody>{keys.data.list.map((item) => <tr key={item.id}><td><strong className="key-name">{item.name || '未命名 Key'}</strong><span className="key-access"><code>{item.access_key}</code><CopyButton text={item.access_key} label="复制 Access Key" compact /></span></td>
            <td><code className="mono">{item.secret_mask}</code></td><td><StatusTag value={item.status} /></td><td className="record-time">{item.expire_time || '长期有效'}</td>
            <td className="admin-actions">
              {/* P3-c：每行一个入口，抽屉自动带上该行的 access_key。 */}
              <button className="text-button" aria-label={`查看 ${item.name || '该 Key'} 的使用方法`} onClick={() => openUsage(item)}>
                <BookOpen size={13} />使用方法
              </button>
              <button className="key-disable" disabled={item.status !== 'enabled' || disabling === item.id} onClick={() => disable(item)}>{disabling === item.id ? '禁用中…' : '禁用'}</button>
            </td></tr>)}</tbody></table></div>}
    </section>
    {creating && <KeyCreateModal onClose={() => setCreating(false)} onCreated={(key) => { setCreated(key); setCreating(false); keys.reload() }} />}
    {created && <KeySecretModal created={created} onClose={() => setCreated(null)}
      onShowUsage={() => { openCreatedUsage(created); setCreated(null) }} />}
    <ApiKeyUsageDrawer open={!!usage} target={usage ?? {}} onClose={() => setUsage(null)} />
  </>
}
