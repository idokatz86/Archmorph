import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

const proxyApiKey = process.env.ARCHMORPH_PROXY_API_KEY

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        headers: proxyApiKey ? { 'X-API-Key': proxyApiKey } : undefined
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
          // prismjs must NOT be chunked separately — language plugins
          // reference a global `Prism` that the app wrapper sets first
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
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json-summary', 'html'],
      reportsDirectory: './coverage',
      include: [
        'src/components/DiagramTranslator/ExportHub.jsx',
        'src/components/DiagramTranslator/LandingZoneViewer.jsx',
        'src/components/DiagramTranslator/useWorkflow.js',
        'src/services/apiClient.js',
        'src/services/errorReporter.js',
        'src/services/sessionCache.js',
      ],
      exclude: [
        'src/**/*.test.{js,jsx}',
        'src/**/__tests__/**',
        'src/test/**',
        'src/generated/**',
      ],
      thresholds: {
        lines: 75,
        functions: 75,
        branches: 70,
        statements: 75,
      },
    },
  }
})
