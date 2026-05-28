import UnoCSS from 'unocss/vite'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue(), UnoCSS()],
  server: {
    host: '0.0.0.0',
    proxy: {
      // 开发环境把 /api 请求转发给 FastAPI，避免浏览器跨域问题。
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
