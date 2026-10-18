import { ChatWorkspace } from '@/features/chat/ChatWorkspace'

export function ChatPage() {
  return (
    <section className="mx-auto max-w-[1500px] px-5 pb-24 pt-12 md:px-10 md:pt-16">
      <p className="mb-4 text-sm text-[#c9f05b]">AICapabilityHub Pro / 能力调试台</p>
      <h1 className="text-4xl font-medium tracking-[-.05em] text-[#f4f4ef] md:text-6xl"><span className="block sm:inline">选定能力，</span>验证每次调用。</h1>
      <p className="mt-6 max-w-2xl text-sm leading-7 text-white/45">
        按能力参数输入，预览积分价格。聊天与文本摘要分别执行，
        结果包含实际费用、调用状态与 requestId。
      </p>
      <ChatWorkspace />
    </section>
  )
}
