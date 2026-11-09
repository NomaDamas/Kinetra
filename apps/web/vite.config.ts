import react from '@vitejs/plugin-react'
import { defineConfig, type Plugin } from 'vite'
import { createReadStream, existsSync, statSync } from 'node:fs'
import { join, normalize } from 'node:path'

// Dev-only: serve apps/web/fixtures/** at /fixtures/** (never part of `vite build`).
function fixtures(): Plugin {
  const root = join(process.cwd(), 'fixtures')
  return {
    name: 'kinetra-dev-fixtures',
    apply: 'serve',
    configureServer(server) {
      server.middlewares.use('/fixtures', (req, res, next) => {
        const rel = normalize(decodeURIComponent((req.url ?? '/').split('?')[0])).replace(/^(\.\.[/\\])+/, '')
        const file = join(root, rel)
        if (!file.startsWith(root) || !existsSync(file) || !statSync(file).isFile()) return next()
        res.setHeader('content-type', file.endsWith('.json') ? 'application/json' : 'application/octet-stream')
        createReadStream(file).pipe(res)
      })
    },
  }
}

export default defineConfig({
  plugins: [react(), fixtures()],
  build: { chunkSizeWarningLimit: 1500 },
})
