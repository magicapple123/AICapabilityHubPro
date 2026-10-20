import { App as AntApp, ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { RouterProvider } from 'react-router-dom'
import { router } from '@/router'

export default function App() {
  return (
    <ConfigProvider locale={zhCN} theme={{
      token: {
        colorPrimary: '#315e4c', colorText: '#272b28', colorTextSecondary: '#6d726d',
        colorBgContainer: '#ffffff', colorBgElevated: '#ffffff',
        colorBorder: '#dedfda', borderRadius: 8, controlHeight: 40,
        fontFamily: 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif',
      },
      components: { Modal: { titleFontSize: 18 }, Drawer: { paddingLG: 24 } },
    }}>
      <AntApp><RouterProvider router={router} /></AntApp>
    </ConfigProvider>
  )
}
