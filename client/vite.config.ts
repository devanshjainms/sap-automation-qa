// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/auth': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/ag-ui': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        // SSE: disable response buffering so events stream in real-time
        configure: (proxy) => {
          proxy.on('proxyRes', (proxyRes) => {
            // Prevent http-proxy from buffering the chunked SSE response
            proxyRes.headers['cache-control'] = 'no-cache';
            proxyRes.headers['x-accel-buffering'] = 'no';
          });
        },
      },
      '/healthz': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
