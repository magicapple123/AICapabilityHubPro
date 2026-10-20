import { ArrowLeft, RefreshCw, SearchX } from 'lucide-react'
import { Link } from 'react-router-dom'

export function NotFoundPage() {
  return <section className="page"><div className="panel empty-state" style={{ minHeight: 430 }}>
    <span className="empty-icon"><SearchX size={24} /></span><h1 className="page-title">这个页面暂时找不到</h1>
    <p>链接可能已变更，你可以回到工作台继续操作。</p><Link to="/" className="button-primary"><ArrowLeft size={15} />返回工作台</Link>
  </div></section>
}
export function RouteFailure() {
  return <main className="empty-state" style={{ minHeight: '100vh' }}><h1 className="page-title">页面暂时无法打开</h1>
    <p>请检查网络连接后重试，已保存的记录仍然保留。</p>
    <button className="button-primary" onClick={() => window.location.reload()}><RefreshCw size={15} />重新加载</button>
    <Link to="/" className="text-link">返回工作台</Link></main>
}
