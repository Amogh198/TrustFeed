/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

const apiTarget = process.env.TRUSTFEED_API_TARGET || 'http://127.0.0.1:8000';
const apiProxy = {
  '/api': { target: apiTarget, changeOrigin: true },
  '/health': { target: apiTarget, changeOrigin: true },
};

// Route local and preview requests through the API so browser hostname/CORS
// differences don't prevent the dashboard from reaching the backend.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, strictPort: true, proxy: apiProxy },
  preview: { port: 5173, strictPort: true, proxy: apiProxy },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.{ts,tsx}'],
  },
});
