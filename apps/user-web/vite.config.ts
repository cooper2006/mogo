import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath } from 'node:url'

const communityProductExtension = fileURLToPath(new URL('./src/product/community.ts', import.meta.url))
const configuredProductExtension = process.env.MOGO_PRODUCT_UI_EXTENSION?.trim()

// https://vitejs.dev/config/
export default defineConfig({
    plugins: [vue()],
    resolve: {
        alias: {
            // 与 admin-web 对齐：`@/xxx` 指向 src，供组件内绝对路径引用（045 资产中心门户页使用）。
            '@': fileURLToPath(new URL('./src', import.meta.url)),
            '@mogo-product-extension': configuredProductExtension || communityProductExtension,
            '@mogo-user-web': fileURLToPath(new URL('./src', import.meta.url)),
            'vue': fileURLToPath(new URL('./node_modules/vue', import.meta.url)),
            'naive-ui': fileURLToPath(new URL('./node_modules/naive-ui', import.meta.url)),
            'axios': fileURLToPath(new URL('./node_modules/axios', import.meta.url)),
        },
    },
    build: {
        target: 'esnext',
        // Disable sourcemap in production to prevent source code leakage (QF-009).
        sourcemap: false,
        // 026 T035: 生产构建优化 —— gzip 体积报告、CSS 代码分割、静态资源内联阈值、
        // 模块预加载 polyfill、带 hash 的 chunk 文件名（CDN 长缓存友好）。
        // 传输层 gzip/brotli 压缩由 nginx/CDN 完成（deploy/nginx/static-assets-cdn.conf）。
        reportCompressedSize: true,
        cssCodeSplit: true,
        assetsInlineLimit: 4096,
        modulePreload: { polyfill: true },
        chunkSizeWarningLimit: 600,
        rollupOptions: {
            output: {
                chunkFileNames: 'assets/[name]-[hash].js',
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
