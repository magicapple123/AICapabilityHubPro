import { ArrowUpRight, History } from 'lucide-react'
import { Link } from 'react-router-dom'
import { PageHeader } from '@/components/PageHeader'
import { ChatWorkspace } from '@/features/chat/ChatWorkspace'

export function ChatPage() {
  return <section className="page chat-page">
    <PageHeader title="在线调试" description="根据能力参数发起调用，查看结果与执行收据。"
      actions={<Link className="button-secondary" to="/usage"><History size={14} />调用记录<ArrowUpRight size={13} /></Link>} />
    <ChatWorkspace />
  </section>
}
