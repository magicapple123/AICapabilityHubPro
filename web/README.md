# Web 前端

基于 React 19、Vite、TypeScript、Tailwind CSS 4、GSAP ScrollTrigger、Ant Design 5、React Router 7、Zustand 和 Axios 的开发者工作台。

## 启动

```powershell
pnpm install
pnpm dev
```

默认访问 <http://localhost:5173>。复制 `.env.example` 为 `.env` 后可配置网关地址；开发阶段 `/api` 由 Vite 代理到 `VITE_DEV_GATEWAY_URL`（默认 `http://localhost:8080`）。Pro 默认 `VITE_USE_MOCK_LOGIN=false`，登录/注册走真实网关；只有显式设置为 `true` 时才使用占位登录。

页面路由：`/login`、`/register` 登录注册、`/` 工作台、`/capabilities` 能力市场、`/chat` 在线调试、`/usage` 调用记录、`/settings` 开发者中心、`/console` 运营后台。已有页面使用旧版真实接口；Pro 的角色权限、Key 兑换和按能力 Schema 调用仍由成员按任务看板实现。模型 Mock 与占位登录是两个独立开关。

## Nginx 生产入口

仓库根目录执行 `docker compose -f deploy/docker-compose.yml up -d --build nginx` 时，Compose 会用 Node 24 构建当前前端，并由 Nginx 托管 `dist`；浏览器访问 <http://localhost>（或 `NGINX_PORT` 配置的端口）。Nginx 将 `/api/**` 同源转发到 Spring Cloud Gateway，前端不需要直连 Python 服务。

生产构建默认使用真实登录。只有脱离后端做纯前端演示时，才在 `deploy/.env` 设置 `VITE_USE_MOCK_LOGIN=true` 后重新构建 Nginx。

## 目录

- `src/api`：Axios 客户端与接口封装
- `src/pages`：登录注册、市场、调试、用量、设置和运营页面入口
- `src/components`：布局及可复用组件
- `src/stores`：Zustand 状态
- `src/router`：路由及登录守卫
- `src/utils`：环境配置工具
