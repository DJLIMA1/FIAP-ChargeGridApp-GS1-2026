/// <reference types="vitest/config" />
import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

const PUBLIC_API = 'https://chargegrid-api-preview-djlima1s-projects.vercel.app'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', 'VITE_')
  const target = env.VITE_API_PROXY || PUBLIC_API
  return {
    plugins: [react()],
    server: {
      port: 5199,
      strictPort: false,
      proxy: {
        '/v1': { target, changeOrigin: true, secure: true },
      },
    },
    preview: {
      port: 5299,
      proxy: { '/v1': { target, changeOrigin: true, secure: true } },
    },
    build: {
      target: 'es2022',
      sourcemap: false,
      assetsInlineLimit: 0,
      chunkSizeWarningLimit: 600,
      rollupOptions: {
        output: {
          // Bibliotecas em chunks próprios: mudam pouco e ficam em cache entre deploys.
          manualChunks(id) {
            if (!id.includes('node_modules')) return undefined
            if (/node_modules\/(react|react-dom|scheduler|react-router|react-router-dom|@remix-run)\//.test(id)) return 'react'
            return 'charts'
          },
        },
      },
    },
    test: {
      environment: 'node',
      include: ['tests/**/*.test.ts'],
    },
  }
})
