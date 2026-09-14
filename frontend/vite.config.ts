import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const BACKEND_TARGET = 'http://localhost:8000'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    allowedHosts: true,
    watch: { usePolling: true, interval: 100 },
    proxy: {
      '/api': {
        target: BACKEND_TARGET,
        changeOrigin: true,
      },
      '/v1': {
        target: BACKEND_TARGET,
        changeOrigin: true,
        ws: true,
      },
      '/assets': {
        target: BACKEND_TARGET,
        changeOrigin: true,
      },
      '/favicon.svg': {
        target: BACKEND_TARGET,
        changeOrigin: true,
      },
      '/apple-touch-icon.png': {
        target: BACKEND_TARGET,
        changeOrigin: true,
      },
      '/.well-known': {
        target: BACKEND_TARGET,
        changeOrigin: true,
      },
      '/omnigent-app': {
        target: BACKEND_TARGET,
        changeOrigin: true,
        ws: true,
      },
      '/c': {
        target: BACKEND_TARGET,
        changeOrigin: true,
        ws: true,
      },
    },
  },
})