import { App as AntApp, ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { RouterProvider } from 'react-router-dom'
import { router } from '@/router'

export default function App() {
  return (
    <ConfigProvider locale={zhCN} theme={{
      token: {
        colorPrimary: '#3a34a8', colorText: '#0e1626', colorTextSecondary: '#46536a',
        colorBgContainer: '#ffffff', colorBgElevated: '#ffffff',
        colorBorder: '#d3d9e5', borderRadius: 8, borderRadiusLG: 12, controlHeight: 40,
        fontFamily: 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei UI", sans-serif',
      },
      components: { Modal: { titleFontSize: 18 }, Drawer: { paddingLG: 24 } },
    }}>
      <AntApp><RouterProvider router={router} /></AntApp>
    </ConfigProvider>
  )
}
