import { lazy } from 'react'
import { createBrowserRouter } from 'react-router-dom'
import { AppShell } from '@/components/AppShell'
import { AuthGuard } from './AuthGuard'
import { LoginPage } from '@/pages/LoginPage'
import { NotFoundPage, RouteFailure } from '@/pages/NotFoundPage'

const Overview = lazy(() => import('@/pages/OverviewPage').then((m) => ({ default: m.OverviewPage })))
const Market = lazy(() => import('@/pages/CapabilitiesPage').then((m) => ({ default: m.CapabilitiesPage })))
const Chat = lazy(() => import('@/pages/ChatPage').then((m) => ({ default: m.ChatPage })))
const Usage = lazy(() => import('@/pages/UsagePage').then((m) => ({ default: m.UsagePage })))
const Settings = lazy(() => import('@/pages/SettingsPage').then((m) => ({ default: m.SettingsPage })))
const Console = lazy(() => import('@/pages/ConsolePage').then((m) => ({ default: m.ConsolePage })))

export const router = createBrowserRouter([
  { path: '/login', element: <LoginPage />, errorElement: <RouteFailure /> },
  { path: '/register', element: <LoginPage /> },
  {
    element: <AuthGuard />, errorElement: <RouteFailure />, children: [{
      element: <AppShell />, children: [
        { index: true, element: <Overview /> },
        { path: 'capabilities', element: <Market /> },
        { path: 'chat', element: <Chat /> },
        { path: 'usage', element: <Usage /> },
        { path: 'settings', element: <Settings /> },
        { path: 'console', element: <Console /> },
        { path: '*', element: <NotFoundPage /> },
      ],
    }],
  },
])
