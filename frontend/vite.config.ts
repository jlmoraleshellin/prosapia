import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: './',
  build: {
    outDir: '../src/prosapia/server/static',
    emptyOutDir: true,
    chunkSizeWarningLimit: 5000,
    rollupOptions: {
      output: { advancedChunks: { groups: [{ name: 'plotly', test: /plotly/ }] } },
    },
  },
  server: { proxy: { '/api': 'http://127.0.0.1:8765' } },
})
