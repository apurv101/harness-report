import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// `npm run build` writes web/dist, which serve.py serves and wrangler deploys.
// `npm run dev` serves the frontend on :5173 and passes the API through to a
// `python3 serve.py` running on :8789, so sign-in and real runs work in dev.
const API = 'http://127.0.0.1:8789'

export default defineConfig({
  plugins: [react()],
  build: { outDir: 'dist', emptyOutDir: true },
  server: {
    port: 5173,
    proxy: Object.fromEntries(['/api', '/auth', '/raw'].map(p => [p, { target: API, changeOrigin: false }])),
  },
})
