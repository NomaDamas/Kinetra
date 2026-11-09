// Separate build for the pitch presenter (present.html). Does not touch the main app build.
// pnpm exec vite build -c vite.present.config.ts   -> ../../out/film/site
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
import { resolve } from 'node:path'

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: resolve(__dirname, '../../out/film/site'),
    emptyOutDir: true,
    chunkSizeWarningLimit: 2000,
    rollupOptions: { input: resolve(__dirname, 'present.html') },
  },
})
