import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath } from 'node:url'

const communityProductExtension = fileURLToPath(new URL('./src/product/community.ts', import.meta.url))
const configuredProductExtension = process.env.MOVO_PRODUCT_UI_EXTENSION?.trim()

// https://vitejs.dev/config/
export default defineConfig({
    plugins: [vue()],
    resolve: {
        alias: {
            '@movo-product-extension': configuredProductExtension || communityProductExtension,
            '@movo-user-web': fileURLToPath(new URL('./src', import.meta.url)),
            'vue': fileURLToPath(new URL('./node_modules/vue', import.meta.url)),
            'naive-ui': fileURLToPath(new URL('./node_modules/naive-ui', import.meta.url)),
            'axios': fileURLToPath(new URL('./node_modules/axios', import.meta.url)),
        },
    },
    build: {
        target: 'esnext',
        // Disable sourcemap in production to prevent source code leakage (QF-009).
        sourcemap: false,
        chunkSizeWarningLimit: 600,
        rollupOptions: {
            output: {
                manualChunks: {
                    'vendor-vue': ['vue'],
                    'vendor-ui': ['naive-ui', '@vicons/ionicons5'],
                    'vendor-editor': ['codemirror', '@codemirror/commands', '@codemirror/lang-python', '@codemirror/state', '@codemirror/view'],
                    'vendor-terminal': ['@xterm/xterm', '@xterm/addon-fit'],
                    'vendor-pdf': ['pdfjs-dist'],
                    'vendor-http': ['axios'],
                    'vendor-highlight': ['highlight.js'],
                },
            },
        },
    },
    optimizeDeps: {
        esbuildOptions: {
            target: 'esnext',
        },
    },
    server: {
        host: '0.0.0.0',
        port: 3000,
        proxy: {
            '/api': {
                target: process.env.VITE_LEGACY_API_TARGET || 'http://127.0.0.1:8000',
                changeOrigin: true,
                rewrite: (path) => path.replace(/^\/api/, ''),
            },
            '/portal-api': {
                target: process.env.VITE_PORTAL_API_TARGET || 'http://127.0.0.1:8100',
                changeOrigin: true,
                rewrite: (path) => path.replace(/^\/portal-api/, ''),
            },
            '/knowledge-api': {
                target: process.env.VITE_KNOWLEDGE_API_TARGET || 'http://127.0.0.1:8100',
                changeOrigin: true,
                rewrite: (path) => path.replace(/^\/knowledge-api/, ''),
            },
            '/sso': {
                target: process.env.VITE_SSO_API_TARGET || 'http://127.0.0.1:8100',
                changeOrigin: true,
                rewrite: (path) => path.replace(/^\/sso/, ''),
            },
            '/aigc': {
                target: process.env.VITE_AIGC_API_TARGET || 'http://127.0.0.1:8000',
                changeOrigin: true,
                rewrite: (path) => path.replace(/^\/aigc/, ''),
            },
            '/askai-api': {
                target: 'http://localhost:8000',
                changeOrigin: true,
                rewrite: (path) => path.replace(/^\/askai-api/, ''),
                ws: true,
            },
            '/admin-api': {
                target: process.env.VITE_ADMIN_API_TARGET || 'http://127.0.0.1:8100',
                changeOrigin: true,
                rewrite: (path) => path.replace(/^\/admin-api/, ''),
            },
        }
    }
})
