# Nginx 镜像同时负责构建并托管 React 静态资源。
# 构建上下文是仓库根目录，由 deploy/docker-compose.yml 指定。

FROM node:24-alpine AS frontend-build

WORKDIR /workspace/web

RUN corepack enable \
    && corepack prepare pnpm@11.24.0 --activate

COPY web/package.json web/pnpm-lock.yaml web/pnpm-workspace.yaml ./
ARG NPM_REGISTRY=https://registry.npmjs.org
RUN pnpm config set registry "${NPM_REGISTRY}" \
    && pnpm config set network-concurrency 4 \
    && pnpm config set fetch-retries 5 \
    && pnpm config set fetch-timeout 300000 \
    && pnpm install --frozen-lockfile

COPY web/ ./

ARG VITE_API_BASE_URL=/api
ARG VITE_USE_MOCK_LOGIN=false
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
ENV VITE_USE_MOCK_LOGIN=${VITE_USE_MOCK_LOGIN}

RUN pnpm build

FROM nginx:1.27-alpine

COPY deploy/nginx/nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=frontend-build /workspace/web/dist /usr/share/nginx/html
