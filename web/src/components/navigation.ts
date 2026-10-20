import { BarChart3, Blocks, FlaskConical, LayoutDashboard, Settings2, SlidersHorizontal } from 'lucide-react'

export const workspaceLinks = [
  { href: '/', label: '工作台', description: '概览、余额和最近活动', icon: LayoutDashboard },
  { href: '/capabilities', label: '能力市场', description: '发现聊天与文本摘要能力', icon: Blocks },
  { href: '/chat', label: '在线调试', description: '填写参数并核对执行结果', icon: FlaskConical },
  { href: '/usage', label: '调用记录', description: '查看用量、费用和调用详情', icon: BarChart3 },
]
export const accountLinks = [
  { href: '/console', label: '运营后台', description: '分类、能力和平台用量', icon: SlidersHorizontal },
  { href: '/settings', label: '账号设置', description: '个人资料、积分和 API Key', icon: Settings2 },
]
export const navigationLinks = [...workspaceLinks, ...accountLinks]
