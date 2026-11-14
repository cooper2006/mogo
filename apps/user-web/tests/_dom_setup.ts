// Provides a browser-like DOM (window/document) for DOMPurify in the Node test
// runner. Injected first by esbuild so `import DOMPurify from 'dompurify'` can
// initialize its sanitizer against a real document.
import { JSDOM } from 'jsdom'
const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
const g = globalThis as any
g.window = dom.window
g.document = dom.window.document
g.HTMLElement = dom.window.HTMLElement
g.Node = dom.window.Node
g.DocumentFragment = dom.window.DocumentFragment
