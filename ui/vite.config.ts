import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: {
      // 后端主服务（FastAPI）
      '/api/task': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/api/upload': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/api/files': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/api/download': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      // 认证微服务
      '/api/auth': { target: 'http://127.0.0.1:8001', changeOrigin: true },
      // WebSocket
      '/ws': { target: 'ws://127.0.0.1:8000', ws: true },
    },
  },
})
