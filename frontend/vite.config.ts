import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig, type Plugin } from 'vite'

const BACKEND_TARGET = 'http://localhost:8000'

const LOOKBEHIND_REWRITES: [string, string][] = [
  ['new RegExp("(?<=1)(?<!1)")', 'new globalThis.RegExp("(?<=1)(?<!1)")'],
  [
    'new RegExp("(?<=[\\\\p{L}\\\\p{N}_])~(?!~)(?=[\\\\p{L}\\\\p{N}_])","gu")',
    '(() => { try { return new globalThis.RegExp("(?<=[\\\\p{L}\\\\p{N}_])~(?!~)(?=[\\\\p{L}\\\\p{N}_])", "gu"); } catch { return /(?!)/gu; } })()',
  ],
  [
    "/(?<=^|\\s|\\p{P}|\\p{S})([-.\\w+]+)@([-\\w]+(?:\\.[-\\w]+)+)/gu",
    '(() => { try { return new globalThis.RegExp("(?<=^|\\\\s|\\\\p{P}|\\\\p{S})([-.\\\\w+]+)@([-\\\\w]+(?:\\\\.[-\\\\w]+)+)", "gu"); } catch { return /(?!)/gu; } })()',
  ],
]
const LOOKBEHIND_REWRITE_MODULES = [
  '/node_modules/marked/',
  '/node_modules/remend/',
  '/node_modules/mdast-util-gfm-autolink-literal/',
]

function isLookbehindRewriteModule(id: string): boolean {
  const normalizedId = id.replaceAll('\\', '/')
  return LOOKBEHIND_REWRITE_MODULES.some((modulePath) => normalizedId.includes(modulePath))
}

function safariLookbehindWorkarounds(): Plugin {
  return {
    name: 'safari-lookbehind-workarounds',
    transform(code, id) {
      if (!isLookbehindRewriteModule(id)) return

      let out = code
      for (const [from, to] of LOOKBEHIND_REWRITES) {
        out = out.replaceAll(from, to)
      }
      if (out === code) return
      return { code: out, map: null }
    },
  }
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [safariLookbehindWorkarounds(), react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src/omnigent'),
    },
  },
  server: {
    host: true,
    allowedHosts: true,
    fs: {
      allow: ['..', '/tmp/omnigent_repo'],
    },
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
      '/auth': {
        target: BACKEND_TARGET,
        changeOrigin: true,
      },
      '/health': {
        target: BACKEND_TARGET,
        changeOrigin: true,
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