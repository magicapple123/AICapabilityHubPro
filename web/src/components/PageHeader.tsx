import type { ReactNode } from 'react'

export function PageHeader({ title, description, actions, eyebrow }: {
  title: string; description?: string; actions?: ReactNode; eyebrow?: string
}) {
  return <header className="page-header"><div>{eyebrow && <p className="eyebrow">{eyebrow}</p>}
    <h1 className="page-title">{title}</h1>{description && <p className="page-description">{description}</p>}</div>
    {actions && <div className="page-actions">{actions}</div>}
  </header>
}
