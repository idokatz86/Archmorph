import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true
      }
    }
  },
  build: {
    outDir: 'dist',
    sourcemap: 'hidden',  // Hidden source maps for error monitoring (#104 — F-013)
    // Issue #182 — Chunk splitting for better caching & smaller initial load
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules/react-dom') || id.includes('node_modules/react/')) {
            return 'vendor-react';
          }
          if (id.includes('node_modules/lucide-react')) {
            return 'vendor-ui';
          }
          // prismjs must NOT be in a separate chunk — language plugins
          // reference a global `Prism` that must be set before they load
          if (id.includes('node_modules/prismjs')) {
            return 'vendor-prism';
          }
        },
      },
    },
    // Inline assets < 4 KB to reduce HTTP requests
    assetsInlineLimit: 4096,
    // Target modern browsers for smaller output
    target: 'es2020',
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/test/setup.js',
    css: true,
    testTimeout: 10000,  // 10s timeout for async tests in CI
  }
})
