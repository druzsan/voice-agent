/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The backend runs on this machine, or next to the dev server in Compose's
// development mode under its service name
const backendUrl = process.env['BACKEND_URL'] ?? 'http://127.0.0.1:8000'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Same route as nginx in the runtime container
    proxy: {
      '/api': { target: backendUrl, ws: true },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
  },
})
