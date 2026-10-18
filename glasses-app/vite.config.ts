import { defineConfig } from 'vite'

export default defineConfig({
  server: {
    // Localhost only. For real glasses, run `npm run dev -- --host` so the phone can reach it.
    port: 5173,
    strictPort: true,
  },
  build: {
    target: 'esnext', // allow top-level await
  },
})
