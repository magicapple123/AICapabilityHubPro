import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'node:path'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '')
  const gatewayUrl = env.VITE_DEV_GATEWAY_URL || 'http://localhost:8080'
  return {
    plugins: [react(), tailwindcss()],
    resolve: { alias: { '@': path.resolve(__dirname, './src') } },
    server: {
      port: Number(env.VITE_PORT || 5173),
      host: 'localhost',
      proxy: {
        '/api': {
          target: gatewayUrl,
          changeOrigin: true,
        },
        // OpenAI 兼容端点：外部客户端（Cherry Studio / Continue / Codex 等）把 Base URL
        // 直接填成 `http://localhost:<dev 端口>/v1`，所以开发服务器必须真实透传到网关，
        // 否则本端口是 Vite SPA，未匹配路径会回 index.html，客户端拿到 HTML 后报
        // “该服务商没有提供模型列表接口”。
        //
        // 用正则键而非字符串 `'/v1'`：字符串键是“前缀匹配”，会把 `/v1abc` 这类同前缀
        // 路径也吞进网关；正则 `^/v1/` 只匹配真正的 /v1/** 端点。
        '^/v1/': {
          target: gatewayUrl,
          changeOrigin: true,
          // `/v1/chat/completions` 与 `/v1/responses` 是真流式（SSE）：
          // http-proxy 是管道直通、不整包缓冲，这里不设 timeout/proxyTimeout，
          // 保证长连接不会被中间层提前掐断。
          ws: false,
          secure: false,
        },
      },
    },
  }
})
