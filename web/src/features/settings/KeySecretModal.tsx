import { App } from 'antd'
import { BookOpen, CheckCheck } from 'lucide-react'
import type { ApiKeyCreated } from '@/api/user'
import { CopyButton } from '@/components/CopyButton'
import { Modal } from '@/components/ui'

export function KeySecretModal({ created, onClose, onShowUsage }: {
  created: ApiKeyCreated; onClose: () => void
  /** P3：直接带去「使用方法」抽屉，那里会自动列出这把 Key 可用的模型。 */
  onShowUsage?: () => void
}) {
  const { modal } = App.useApp()
  const requestClose = () => modal.confirm({
    title: '已经保存好密钥了吗？', content: '关闭后无法再次查看 Secret Key。如尚未保存，请先复制。',
    okText: '已保存，关闭', cancelText: '继续查看', onOk: onClose,
  })
  return <Modal title="访问凭证已创建" open onClose={requestClose}
    footer={<div className="form-actions">
      {onShowUsage && <button className="button-secondary" onClick={onShowUsage}><BookOpen size={15} />查看使用方法</button>}
      <button className="button-primary" onClick={onClose}><CheckCheck size={15} />我已安全保存</button>
    </div>}>
    <p className="key-secret-notice">Secret Key 仅展示这一次，请立即复制并妥善保存。</p>
    <div className="key-secret-block"><div><span>Access Key</span><CopyButton text={created.access_key} label="复制 Access Key" /></div><code>{created.access_key}</code></div>
    <div className="key-secret-block"><div><span>Secret Key</span><CopyButton text={created.secret_key} label="复制 Secret Key" /></div><code>{created.secret_key}</code></div>
    {/* P3-a：最容易踩的坑就写在下发密钥的地方，而不是只放在设置页顶部。 */}
    <p className="inline-note">Secret 用于 OpenAI 兼容（<code>/v1</code>），exchange 换来的 JWT 用于平台 API（<code>/api</code>），两者不可互换。</p>
    <p className="inline-note">不要分享此密钥，也不要将其写入浏览器持久化存储或公开仓库。</p>
  </Modal>
}
