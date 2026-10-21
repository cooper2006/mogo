import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';
import path from 'node:path';

const productExtensionEnv = process.env.MOGO_ADMIN_PRODUCT_UI_EXTENSION?.trim();
const productExtensionPath = productExtensionEnv
  ? path.resolve(productExtensionEnv)
  : path.resolve(__dirname, './src/product/community.ts');

export default defineConfig(({ command }) => ({
  // The production admin app is always mounted below /admin by the gateway.
  // Keep the build safe even when a Docker/build environment omits the variable.
  base: process.env.VITE_BASE_PATH || (command === 'build' ? '/admin/' : '/'),
  plugins: [vue()],
  build: {
    // Disable sourcemap in production to prevent source code leakage (QF-009).
    sourcemap: false,
    chunkSizeWarningLimit: 600,
    rollupOptions: {
      output: {
        manualChunks: {
          'vendor-vue': ['vue', 'vue-router', 'pinia'],
          'vendor-ui': ['naive-ui'],
          'vendor-editor': ['codemirror', '@codemirror/commands', '@codemirror/lang-python', '@codemirror/state', '@codemirror/view'],
          'vendor-pdf': ['pdfjs-dist'],
          'vendor-http': ['axios'],
        },
      },
    },
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
      '@mogo-admin-product-extension': productExtensionPath,
      '@mogo-admin-web': path.resolve(__dirname, './src'),
      'vue': path.resolve(__dirname, './node_modules/vue'),
      'naive-ui': path.resolve(__dirname, './node_modules/naive-ui'),
      'axios': path.resolve(__dirname, './node_modules/axios'),
    },
  },
  server: {
    host: '0.0.0.0',
    port: 3100,
    proxy: {
      '/admin-api': {
        target: process.env.VITE_ADMIN_API_TARGET || 'http://127.0.0.1:8100',
        changeOrigin: true,
        rewrite: (sourcePath) => sourcePath.replace(/^\/admin-api/, ''),
      },
      '/askai-api': {
        target: process.env.VITE_CHAT_API_TARGET || 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: (sourcePath) => sourcePath.replace(/^\/askai-api/, ''),
      },
    },
  },
}));
