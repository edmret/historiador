import { fileURLToPath, URL } from 'node:url'

import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

/**
 * The daemon's default bind address (ARCHITECTURE.md §8). Proxying `/api` and
 * `/ws` through the dev server keeps the dashboard same-origin in development,
 * so there is no CORS handshake and no environment-specific base URL in the
 * client code: it always talks to relative `/api/...` and `/ws/...`.
 */
const DAEMON_ORIGIN = 'http://127.0.0.1:8080'

export default defineConfig({
  plugins: [react(), tailwindcss()],

  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },

  server: {
    port: 5273,
    strictPort: false,
    proxy: {
      '/api': {
        target: DAEMON_ORIGIN,
        changeOrigin: true,
      },
      // `/ws/runs` is a WebSocket upgrade — `ws: true` is what makes the
      // snapshot-then-delta stream (ARCHITECTURE.md §7) work in dev.
      '/ws': {
        target: DAEMON_ORIGIN,
        changeOrigin: true,
        ws: true,
      },
    },
  },

  build: {
    target: 'es2022',
    sourcemap: true,
    outDir: 'dist',
  },
})
