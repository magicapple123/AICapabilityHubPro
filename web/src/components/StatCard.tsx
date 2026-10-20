import type { ReactNode } from 'react'

export function StatCard({ title, value, detail, loading = false }: {
  title: string; value: ReactNode; detail: ReactNode; icon?: ReactNode; accent?: boolean; loading?: boolean
}) {
  return <article className="stat-card"><p className="stat-label">{title}</p>
    <div className="stat-value">{loading ? <span className="skeleton stat-skeleton" /> : value}</div>
    <div className="stat-detail">{detail}</div>
  </article>
}
