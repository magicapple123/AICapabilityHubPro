import { Drawer, Tabs } from 'antd'
import { AlertTriangle, KeyRound, Terminal } from 'lucide-react'
import { useEffect, useState } from 'react'
import axios from 'axios'
import { request } from '@/api/client'
import { CopyButton } from '@/components/CopyButton'
import { ErrorNote, Loading } from '@/components/ui'
import './api-key-usage.css'

/** 登录后即可读的对外模型名清单（capability-service，P3 新增）。 */
interface PublishedModel {
  alias: string
  capability_id: number
  name: string
}

export interface ApiKeyUsageTarget {
  /** 该行的 access_key；没有选中具体 Key 时为空，展示通用占位。 */
  accessKey?: string
  keyName?: string
  /** 仅在"刚创建完"的弹窗里由内存传入；绝不从列表接口读取、也不落 localStorage。 */
  secretKey?: string
}

const PLACEHOLDER_ACCESS = 'ak_你的AccessKey'
const PLACEHOLDER_SECRET = 'sk_你的Secret（仅创建时可见）'
const PLACEHOLDER_TOKEN = '<exchange 换来的 JWT>'

function siteBaseUrl(): string {
  const apiBase = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/+$/, '')
  const prefix = apiBase.endsWith('/api') ? apiBase.slice(0, -4) : ''
  return `${window.location.origin}${prefix}`
}

async function loadModels(secretKey?: string): Promise<PublishedModel[]> {
  // 有明文 Secret（刚创建完）时直接问 /v1/models，拿到的是"这把 Key 真正能用的模型"。
  if (secretKey) {
    try {
      const response = await axios.get<{ data: { id: string }[] }>(
        `${siteBaseUrl()}/v1/models`,
        { headers: { Authorization: `Bearer ${secretKey}` }, timeout: 8000 },
      )
      return response.data.data.map((item) => ({
        alias: item.id, capability_id: 0, name: '',
      }))
    } catch {
      // 开发环境没有代理 /v1、或 Secret 过期：退回平台侧清单，不让抽屉整体报错。
    }
  }
  const data = await request<{ list: PublishedModel[] }>({
    method: 'GET', url: '/capability/models',
  })
  return data.list
}

function CurlBlock({ title, code }: { title: string; code: string }) {
  return (
    <div className="usage-curl">
      <div className="usage-curl-head"><span>{title}</span><CopyButton text={code} label="复制 curl" /></div>
      <pre><code>{code}</code></pre>
    </div>
  )
}

function ModelList({ models, loading, error }: {
  models: PublishedModel[]; loading: boolean; error: string
}) {
  if (loading) return <Loading label="正在读取可用模型…" />
  if (error) return <ErrorNote message={error} />
  if (!models.length) {
    return <p className="usage-hint">平台还没有对外发布任何 chat 模型。请联系管理员在「能力管理」里填写「对外模型名」。</p>
  }
  return (
    <ul className="usage-models">
      {models.map((item) => (
        <li key={`${item.alias}-${item.capability_id}`}>
          <code>{item.alias}</code>
          {item.name ? <span className="muted"> {item.name}</span> : null}
        </li>
      ))}
    </ul>
  )
}

export function ApiKeyUsageDrawer({ open, onClose, target }: {
  open: boolean; onClose: () => void; target: ApiKeyUsageTarget
}) {
  const [models, setModels] = useState<PublishedModel[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const base = siteBaseUrl()
  const accessKey = target.accessKey || PLACEHOLDER_ACCESS
  const secret = target.secretKey || PLACEHOLDER_SECRET
  const model = models[0]?.alias || 'deepseek-flash'

  useEffect(() => {
    if (!open) return
    let alive = true
    setLoading(true)
    setError('')
    loadModels(target.secretKey)
      .then((list) => { if (alive) setModels(list) })
      .catch((cause: unknown) => {
        if (alive) setError(cause instanceof Error ? cause.message : '可用模型读取失败')
      })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [open, target.secretKey])

  const openaiCurl = [
    `curl ${base}/v1/chat/completions \\`,
    '  -H "Authorization: Bearer ' + (target.secretKey || PLACEHOLDER_SECRET) + '" \\',
    '  -H "Content-Type: application/json" \\',
    `  -d '{"model":"${model}","messages":[{"role":"user","content":"你好"}]}'`,
  ].join('\n')

  const platformExchangeCurl = [
    `curl -X POST ${base}/api/user/apikeys/exchange \\`,
    '  -H "Content-Type: application/json" \\',
    `  -d '{"access_key":"${accessKey}","secret_key":"${secret}"}'`,
  ].join('\n')

  const platformChatCurl = [
    `curl -X POST ${base}/api/chat/completions \\`,
    `  -H "Authorization: Bearer ${PLACEHOLDER_TOKEN}" \\`,
    '  -H "Content-Type: application/json" \\',
    '  -d \'{"capability_id":1,"input":{"messages":[{"role":"user","content":"你好"}]}}\'',
  ].join('\n')

  return (
    <Drawer
      title={target.keyName ? `使用方法 · ${target.keyName}` : 'API Key 使用方法'}
      open={open}
      onClose={onClose}
      width={640}
      destroyOnHidden
    >
      <div className="usage-drawer">
        <div className="usage-warn">
          <AlertTriangle size={16} />
          <div>
            <strong>两套凭证不可互换</strong>
            <p><code>sk_...</code>（Secret）只能用于 <code>/v1/**</code>；
              exchange 换来的 JWT 只能用于 <code>/api/**</code>。
              把 JWT 填进 <code>/v1</code> 会得到 <code>1003 API Key 凭证无效</code>。</p>
          </div>
        </div>

        <div className="usage-facts">
          <div><span>Access Key</span><code>{accessKey}</code>
            {target.accessKey ? <CopyButton text={target.accessKey} label="复制" compact /> : null}</div>
          <div><span>Secret</span><code className="mono">
            {target.secretKey ? target.secretKey : 'sk_****（仅创建时可见，忘记需重建）'}</code></div>
          <div><span>Base URL</span><code>{base}</code></div>
        </div>

        <Tabs
          items={[
            {
              key: 'openai', label: 'OpenAI 兼容',
              children: (
                <div className="usage-section">
                  <p className="usage-hint">端点 <code>/v1/chat/completions</code>，
                    请求头带 Secret；<code>model</code> 必须是下面列出的平台别名，不能填上游真实模型名。</p>
                  <ModelList models={models} loading={loading} error={error} />
                  <CurlBlock title="OpenAI 兼容调用" code={openaiCurl} />
                  <p className="usage-hint">返回体带 <code>platform_request_id</code> 与
                    <code>platform_cost</code>，可直接与调用记录对账。</p>
                </div>
              ),
            },
            {
              key: 'platform', label: '平台 API',
              children: (
                <div className="usage-section">
                  <p className="usage-hint">先用 access_key + Secret 换一个短 JWT（默认 15 分钟、
                    最多 1 小时），再用它调 <code>/api/**</code>。</p>
                  <CurlBlock title="① 换取 JWT" code={platformExchangeCurl} />
                  <CurlBlock title="② 调用平台接口" code={platformChatCurl} />
                  <p className="usage-hint">第一步响应里的 <code>data.token</code> 就是第二步的
                    <code>Authorization</code>；JWT 不要用于 <code>/v1</code>。</p>
                </div>
              ),
            },
            {
              key: 'client', label: '客户端配置',
              children: (
                <div className="usage-section">
                  <p className="usage-hint">Cherry Studio / Continue 这类客户端只填三样：</p>
                  <table className="usage-table">
                    <tbody>
                      <tr><th>Base URL</th><td><code>{base}/v1</code></td></tr>
                      <tr><th>API Key</th><td><code>{target.secretKey ? 'sk_...（刚创建的 Secret）' : 'sk_...（你的 Secret）'}</code></td></tr>
                      <tr><th>Model</th><td><code>{model}</code></td></tr>
                    </tbody>
                  </table>
                  <p className="usage-hint"><KeyRound size={13} /> 模型下拉框里看不到某个能力时，
                    先确认它在「能力管理」里已上架并填了「对外模型名」。</p>
                  <p className="usage-hint"><Terminal size={13} /> Codex 等 Responses 客户端把
                    Base URL 填到 <code>/v1</code> 即可，模型名同样用上面的平台别名。</p>
                </div>
              ),
            },
          ]}
        />
      </div>
    </Drawer>
  )
}
