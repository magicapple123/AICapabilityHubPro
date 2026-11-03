import { Modal as AntModal } from 'antd'
import { AlertCircle } from 'lucide-react'
import type { ReactNode } from 'react'

/**
 * P9.7：登记表单需要 720px 承载两列。
 * `components/ui.tsx` 的 Modal 固定 560 且不属于本次改动范围，这里用 antd 原生
 * Modal 复刻同样的居中 + 可滚动 body，宽度独立控制。
 */
export function EditorModal({ title, onClose, children }: {
  title: string; onClose: () => void; children: ReactNode
}) {
  return <AntModal title={title} open centered width={720} onCancel={onClose} footer={null}
    className="capability-editor-modal"
    styles={{ body: { paddingTop: 18, paddingInline: 24, paddingBottom: 0, maxHeight: 'calc(100vh - 190px)', overflowY: 'auto' } }}>
    {children}
  </AntModal>
}

/** P9.4：字段级错误，紧贴出错的输入项。 */
export function FieldError({ message }: { message?: string }) {
  if (!message) return null
  return <p className="field-error" role="alert"><AlertCircle size={12} /><span>{message}</span></p>
}

/** 语义分组容器：执行配置 / 计价 / 展示 / 基本。 */
export function FormSection({ title, description, children }: {
  title: string; description?: string; children: ReactNode
}) {
  return <section className="cap-section">
    <h3 className="cap-section-title">{title}</h3>
    {description && <p className="cap-section-hint">{description}</p>}
    <div className="cap-section-body">{children}</div>
  </section>
}
