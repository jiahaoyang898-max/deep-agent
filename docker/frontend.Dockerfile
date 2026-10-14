# ---- 前端构建 + Nginx 托管 ----
FROM node:22-alpine AS build

WORKDIR /app

# 构建期开关：登录页是否展示演示账号块（demo / demo123456）
#   默认 true = 展示（当前 8080 演示环境用的就是默认值）
#   关闭方式：docker compose build --build-arg VITE_SHOW_DEMO=false frontend
#   注意：Vite 在构建时把该值内联进产物，改了必须重新构建才生效。
ARG VITE_SHOW_DEMO=true
ENV VITE_SHOW_DEMO=${VITE_SHOW_DEMO}

COPY ui/package.json ui/package-lock.json ./
RUN npm config set registry https://registry.npmmirror.com && npm ci || npm install

COPY ui/ ./
RUN npm run build

# ---- 运行时 ----
FROM nginx:1.27-alpine

COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
