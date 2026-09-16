# FinSage Web 前端镜像（前后端分离，T1107 扩展）
# 构建上下文 = 项目根 `docker compose build web`
# 入口：Next.js `next start`（端口 3000）。
# 构建时注入 NEXT_PUBLIC_API_BASE_URL / NEXT_PUBLIC_SSE_BASE_URL（浏览器可达后端地址）。

# ---- Stage 1: 构建 ----
FROM node:20-alpine AS builder
WORKDIR /app

# 先复制 package 文件安装依赖（利用层缓存，避免每次改源码重装）
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci

# 复制前端源码
COPY apps/web/ ./

# 构建时注入 API/SSE 地址（浏览器经 localhost:<FIN_PORT> 访问后端容器）。
# 端口经 build arg 传入：NEXT_PUBLIC_* 为构建期内联，换端口必须重建镜像。
# 默认 8237；若宿主该端口被系统保留（Windows Hyper-V 动态端口段常见），
# 用 .env 的 FIN_PORT 换端口并由 docker-compose.override.yml 透传。
ARG API_BASE_URL=http://localhost:8237/api/v1
ENV NEXT_PUBLIC_API_BASE_URL=$API_BASE_URL
ENV NEXT_PUBLIC_SSE_BASE_URL=$API_BASE_URL
RUN npm run build

# ---- Stage 2: 运行 ----
FROM node:20-alpine
WORKDIR /app
ENV NODE_ENV=production

COPY --from=builder /app/package.json ./
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/next.config.mjs ./

EXPOSE 3000
CMD ["npm", "run", "start"]
