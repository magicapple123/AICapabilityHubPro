import { App } from 'antd'
import { KeyRound, Plus, ShieldCheck } from 'lucide-react'
import { useState } from 'react'
import { disableApiKey, fetchApiKeys, type ApiKeyCreated, type ApiKeyItem } from '@/api/user'
import { CopyButton } from '@/components/CopyButton'
import { EmptyNote, ErrorNote, Loading, StatusTag } from '@/components/ui'
import { useAsyncResource } from '@/hooks/useAsyncResource'
import { KeyCreateModal } from './KeyCreateModal'
import { KeySecretModal } from './KeySecretModal'

export function ApiKeySettings() {
  const keys = useAsyncResource(fetchApiKeys)
  const [creating, setCreating] = useState(false)
  const [created, setCreated] = useState<ApiKeyCreated | null>(null)
  const [disabling, setDisabling] = useState<number | null>(null)
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
  return <>
    <div className="key-notice"><ShieldCheck size={19} /><div><strong>妥善保管访问凭证</strong><p>Secret Key 仅在创建时展示一次。请将其保存在安全的位置，避免写入前端代码或公开仓库。</p><p>使用 access_key 和 Secret Key，以 JSON POST 到 <code>/api/user/apikeys/exchange</code>，请求体为 <code>{'{"access_key":"…","secret_key":"…"}'}</code>。取响应 <code>data.token</code> 并以 <code>Authorization: Bearer &lt;token&gt;</code> 调用 API。Token 默认 15 分钟、最多 1 小时；以 <code>expires_in</code> / <code>expire_at</code>（UTC）为准，且不会晚于 Key 过期时间。Key 期限按北京时间设置。禁用 Key 后不能再兑换；已签发 Token 到期前仍可使用。不要将 Secret 写入 URL、日志、localStorage 或持久化配置。</p></div></div>
    <section className="panel"><div className="panel-head"><div><h2>API Key 管理</h2><p>为不同用途创建独立凭证，按需禁用</p></div><button className="button-primary" onClick={() => setCreating(true)}><Plus size={15} />新建 API Key</button></div>
      {keys.loading ? <Loading label="正在加载访问凭证…" /> : keys.error ? <div className="panel-body"><ErrorNote message={keys.error} onRetry={keys.reload} /></div> :
        !keys.data?.list.length ? <EmptyNote message="还没有访问凭证。创建一个 API Key，集中管理你的访问授权。"
          action={<button className="button-secondary" onClick={() => setCreating(true)}><KeyRound size={14} />创建第一个 API Key</button>} /> :
        <div className="data-table-wrap"><table className="data-table key-table"><thead><tr><th>名称 / Access Key</th><th>Secret Key</th><th>状态</th><th>有效期</th><th>操作</th></tr></thead>
          <tbody>{keys.data.list.map((item) => <tr key={item.id}><td><strong className="key-name">{item.name || '未命名 Key'}</strong><span className="key-access"><code>{item.access_key}</code><CopyButton text={item.access_key} label="复制 Access Key" compact /></span></td>
            <td><code className="mono">{item.secret_mask}</code></td><td><StatusTag value={item.status} /></td><td className="record-time">{item.expire_time || '长期有效'}</td>
            <td><button className="key-disable" disabled={item.status !== 'enabled' || disabling === item.id} onClick={() => disable(item)}>{disabling === item.id ? '禁用中…' : '禁用'}</button></td></tr>)}</tbody></table></div>}
    </section>
    {creating && <KeyCreateModal onClose={() => setCreating(false)} onCreated={(key) => { setCreated(key); setCreating(false); keys.reload() }} />}
    {created && <KeySecretModal created={created} onClose={() => setCreated(null)} />}
  </>
}
