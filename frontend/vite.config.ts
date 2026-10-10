import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'

export default defineConfig({
  base: '/kb-management/',
  plugins: [vue()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src')
    }
  },
  server: {
    host: '0.0.0.0',
    port: 9013,
    proxy: {
      '/kb-management/api': {
        target: 'http://127.0.0.1:9012',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/kb-management/, '')
      }
    }
  }
})
