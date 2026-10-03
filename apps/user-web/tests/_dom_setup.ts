// Provides a browser-like DOM (window/document) for DOMPurify in the Node test
// runner. Injected first by esbuild so `import DOMPurify from 'dompurify'` can
// initialize its sanitizer against a real document.
import { createRequire } from 'node:module'
const require = createRequire(import.meta.url)
const jsdomPath = require.resolve('jsdom', {
  paths: ['/Users/cooper/Github/mogo/apps/user-web/node_modules/.pnpm/jsdom@26.1.0_canvas@3.2.3/node_modules/jsdom'],
})
const { JSDOM } = require(jsdomPath)
const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
const g = globalThis as any
g.window = dom.window
g.document = dom.window.document
g.HTMLElement = dom.window.HTMLElement
g.Node = dom.window.Node
g.DocumentFragment = dom.window.DocumentFragment
