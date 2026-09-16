import { createBrowserRouter } from 'react-router-dom'
import { AppShell } from '@/components/AppShell'
import { AuthGuard } from './AuthGuard'
import { LoginPage } from '@/pages/LoginPage'
import { OverviewPage } from '@/pages/OverviewPage'
import { CapabilitiesPage } from '@/pages/CapabilitiesPage'
import { ChatPage } from '@/pages/ChatPage'
import { UsagePage } from '@/pages/UsagePage'
import { SettingsPage } from '@/pages/SettingsPage'
import { ConsolePage } from '@/pages/ConsolePage'

export const router = createBrowserRouter([
  // 登录与注册共用同一组件，由路径决定模式。
  { path: '/login', element: <LoginPage /> },
  { path: '/register', element: <LoginPage /> },
  {
    element: <AuthGuard />,
    children: [
      {
        element: <AppShell />,
        children: [
          { index: true, element: <OverviewPage /> },
          { path: 'capabilities', element: <CapabilitiesPage /> },
          { path: 'chat', element: <ChatPage /> },
          { path: 'usage', element: <UsagePage /> },
          { path: 'settings', element: <SettingsPage /> },
          { path: 'console', element: <ConsolePage /> },
        ],
      },
    ],
  },
  { path: '*', element: <LoginPage /> },
])
