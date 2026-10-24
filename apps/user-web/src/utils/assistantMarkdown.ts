/** Shared Markdown projection for streaming and completed assistant content. */

import DOMPurify from 'dompurify'
import { projectSafeMarkdownLinks } from './safeMarkdownLinks'

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;')
}

// 统计正则匹配次数（无匹配时返回 0）。
function countMatches(content: string, re: RegExp): number {
  return content.match(re)?.length || 0
}

// Markdown 结构性信号：标题、列表、分隔线、hr 标签。
function countMarkdownSignals(content: string): number {
  return countMatches(content, /^#{1,6}\s+/gm)
    + countMatches(content, /^\s*[-*]\s+/gm)
    + countMatches(content, /^\s*[–—]\s+/gm)
    + countMatches(content, /^\s*\d+\.\s+/gm)
    + countMatches(content, /^\s*---+\s*$/gm)
    + countMatches(content, /<hr\b[^>]*>/gi)
}

// 段落信号：句末标点与空行。
function countParagraphSignals(content: string): number {
  return countMatches(content, /[。！？.!?]\s*(?:\n|$)/g) + countMatches(content, /\n\s*\n/g)
}

// 代码信号：语言关键字、符号与 HTML 标签。
function countCodeSignals(content: string): number {
  return countMatches(content, /\b(function|class|const|let|var|def|import|return|if|else|for|while|try|catch)\b/g)
    + countMatches(content, /[{};=]/g)
    + countMatches(content, /<\s*(script|style|div|span|table|tr|td|th)\b/gi)
}

// 密集 Markdown 正文：结构信号足、段落信号存在、代码信号有限。
function isDenseMarkdownProse(markdownSignals: number, paragraphSignals: number, codeSignals: number): boolean {
  return markdownSignals >= 2 && paragraphSignals >= 1 && codeSignals <= 12
}

// 稀疏 Markdown 正文：结构信号多、代码信号有限。
function isSparseMarkdownProse(markdownSignals: number, codeSignals: number): boolean {
  return markdownSignals >= 3 && codeSignals <= 16
}

// 显式声明为纯文本语言时的正文判定。
function isDeclaredTextProse(language: string, markdownSignals: number, codeSignals: number): boolean {
  return ['', 'text', 'plaintext', 'markdown', 'md'].includes(language) && markdownSignals >= 1 && codeSignals <= 20
}

/** Detect if code block content is actually prose/markdown rather than code. */
function isProseContent(content: string, language: string): boolean {
  const markdownSignals = countMarkdownSignals(content)
  const paragraphSignals = countParagraphSignals(content)
  const codeSignals = countCodeSignals(content)
  return isDenseMarkdownProse(markdownSignals, paragraphSignals, codeSignals)
    || isSparseMarkdownProse(markdownSignals, codeSignals)
    || isDeclaredTextProse(language, markdownSignals, codeSignals)
}

/** Render a fenced code block, detecting prose vs code. */
function renderCodeBlock(content: string, language: string, stash: (html: string) => string): string {
  const trimmed = content.trim()
  const lang = language.trim().toLowerCase()
  if (isProseContent(trimmed, lang)) return trimmed
  const label = lang ? lang.toUpperCase() : 'TEXT'
  return stash(`
    <div class="assistant-code-block my-4 rounded-lg overflow-hidden group">
      <div class="assistant-code-header flex items-center justify-between px-3 py-1.5"><span class="assistant-code-language text-xs font-medium select-none">${label}</span></div>
      <div class="assistant-code-scroll p-3 overflow-x-auto"><pre class="assistant-code-content text-sm font-mono leading-relaxed whitespace-pre table min-w-full">${escapeHtml(trimmed)}</pre></div>
    </div>
  `)
}

export function normalizeAssistantContent(content: string): string {
  if (!content) return content
  const lines = content.replace(/<br\s*\/?>/gi, '\n').split('\n')
  const result: string[] = []
  let inCodeBlock = false
  for (const line of lines) {
    if (line.trim().startsWith('```')) {
      inCodeBlock = !inCodeBlock
      result.push(line)
      continue
    }
    if (inCodeBlock) {
      result.push(line)
      continue
    }
    const trimmed = line.trim()
    if (trimmed && result[result.length - 1]?.trim() === trimmed) continue
    result.push(line)
  }
  return result.join('\n')
}

export function sanitizeMermaid(code: string): string {
  let text = code.replace(/–/g, '-').replace(/\u00a0/g, ' ').replace(/\r/g, '')
  text = text.replace(/^\s*subgraph\s+([^"\n]+)$/gm, (match, title) => {
    const value = String(title || '').trim()
    return !value || value.startsWith('"') ? match : `subgraph "${value}"`
  })
  return text.replace(/(\[|\(|\{)([^\])\n]+)(\]|\)|})/g, (match, open, content, close) => {
    let value = String(content || '').trim()
    if (value.startsWith('"') && value.endsWith('"')) return match
    value = value.replace(/"/g, "'")
    return `${open}"${value}"${close}`
  })
}

const FILE_EXTENSION = /\.(?:[cm]?[jt]sx?|vue|svelte|py|pyi|go|rs|java|kt|kts|swift|c|cc|cpp|cxx|h|hh|hpp|cs|php|rb|sh|bash|zsh|fish|ps1|sql|html?|css|scss|sass|less|json|ya?ml|toml|ini|conf|env|md|mdx|txt|xml|graphql|gql|proto|dockerfile)$/i
const WELL_KNOWN_FILE = /^(?:README|CHANGELOG|LICENSE|Makefile|Dockerfile|Procfile|Gemfile|Rakefile)(?:\.[a-z0-9_-]+)?$/i

export function workspaceFileReference(value: string): string | null {
  let path = value.trim().replace(/\\/g, '/')
  if (!path || /[\s{}"'<>]/.test(path) || path.startsWith('/') || /^[a-z]+:\/\//i.test(path)) return null
  path = path.replace(/^\.\//, '').replace(/:(\d+)(?::\d+)?$/, '')
  if (!path || path.split('/').some(part => !part || part === '.' || part === '..')) return null
  const name = path.split('/').at(-1) || ''
  return FILE_EXTENSION.test(name) || WELL_KNOWN_FILE.test(name) ? path : null
}

export function renderAssistantMarkdown(text: string, options: { workspaceFileReferences?: boolean } = {}): string {
  let html = normalizeAssistantContent(text)
  const blocks: string[] = []
  const stash = (value: string) => {
    const key = `__BLOCK_PLACEHOLDER_${blocks.length}__`
    blocks.push(value)
    return key
  }

  html = html.replace(/```\s*skill\s*([\s\S]*?)```/g, (_match, code) => stash(`
    <div class="assistant-code-block assistant-code-block--skill my-4 rounded-lg overflow-hidden">
      <div class="assistant-code-header flex items-center px-3 py-2">
        <span class="assistant-code-language text-xs font-bold uppercase tracking-wider">Skill Definition</span>
      </div>
      <div class="assistant-code-scroll p-3 overflow-x-auto"><pre class="assistant-code-content text-xs font-mono leading-relaxed whitespace-pre">${escapeHtml(String(code || '').trim())}</pre></div>
    </div>
  `))

  html = html.replace(/```\s*mermaid\s*([\s\S]*?)```/g, (_match, code) => {
    const safe = sanitizeMermaid(String(code || '').trim())
    return stash(`<div class="mermaid" data-raw="${encodeURIComponent(safe)}">${safe}</div>`)
  })
  html = html.replace(/(?:`{2,4})\s*chart\s*([\s\S]*?)(?:`{2,4})/g, (_match, code) => {
    const json = String(code || '').trim()
    return stash(`<div class="chart-container" style="height:360px"><canvas class="chart-block" data-chart="${encodeURIComponent(json)}"></canvas></div>`)
  })
  html = html.replace(/!\[(.*?)\]\((.*?)\)/g, '<img alt="$1" src="$2" style="max-width:100%; border-radius:12px;" />')
  html = html.replace(/^---+$/gm, '<hr class="my-4 border-gray-300"/>')
  html = html.replace(/```\s*([\s\S]*?\|[\s\S]*?\n[\s\S]*?\|[\s\S]*?)```/g, (_match, table) => String(table || '').trim())

  html = html.replace(/```([a-zA-Z0-9_-]*)\s*([\s\S]*?)```/g, (_match, lang, code) => {
    return renderCodeBlock(String(code || ''), String(lang || ''), stash)
  })

  html = html.replace(/`([^`]+)`/g, (_match, raw) => {
    const content = String(raw || '')
    const filePath = options.workspaceFileReferences ? workspaceFileReference(content) : null
    if (filePath) {
      return `<code class="assistant-inline-code assistant-file-reference" data-workspace-file="${escapeHtml(filePath)}" role="button" tabindex="0">${escapeHtml(content)}</code>`
    }
    return `<code class="assistant-inline-code">${escapeHtml(content)}</code>`
  })
  html = projectSafeMarkdownLinks(html, (label, href) => stash(
    `<a href="${href}" target="_blank" rel="noopener noreferrer nofollow" class="text-blue-600 hover:text-blue-500 underline underline-offset-2">${label}</a>`,
  ))
  html = html.replace(/\|(.+)\|/g, (_match, content) => {
    const cells = String(content).split('|').map(cell => cell.trim()).filter(Boolean)
    return `<tr>${cells.map(cell => `<td class="border border-gray-300 px-3 py-2">${cell}</td>`).join('')}</tr>`
  })
  html = html.replace(/(<tr>.*<\/tr>\n?)+/g, (match) => {
    const rows = match.split('\n').filter(row => row.trim())
    if (rows.length > 1 && rows[1].includes('---')) {
      const header = rows[0].replace(/<td/g, '<th').replace(/<\/td>/g, '</th>').replace(/border-gray-300/g, 'border-gray-300 bg-gray-100 font-bold')
      return `<table class="w-full border-collapse my-4">${header}${rows.slice(2).join('\n')}</table>`
    }
    return `<table class="w-full border-collapse my-4">${match}</table>`
  })
  html = html.replace(/^\s*####\s+(.+)$/gim, '<h4 class="text-base font-semibold mt-3 mb-2">$1</h4>')
  html = html.replace(/^\s*###\s+(.+)$/gim, '<h3 class="text-lg font-bold mt-4 mb-2">$1</h3>')
  html = html.replace(/^\s*##\s+(.+)$/gim, '<h2 class="text-xl font-bold mt-4 mb-2">$1</h2>')
  html = html.replace(/^\s*#\s+(.+)$/gim, '<h1 class="text-2xl font-bold mt-4 mb-2">$1</h1>')
  html = html.replace(/\*\*(.*?)\*\*/g, '<strong class="font-bold">$1</strong>')
  html = html.replace(/\*(.*?)\*/g, '<em class="italic">$1</em>')
  html = html.replace(/^- (.*$)/gim, '<li class="list-disc ml-6">$1</li>')
  html = html.replace(/^\d+\. (.*$)/gim, '<li class="list-decimal ml-6">$1</li>')
  html = html.replace(/(<li class="list-disc[^>]*>.*<\/li>\n?)+/g, match => `<ul class="my-2">${match.replace(/\n/g, '')}</ul>`)
  html = html.replace(/(<li class="list-decimal[^>]*>.*<\/li>\n?)+/g, match => `<ol class="my-2">${match.replace(/\n/g, '')}</ol>`)
  html = html.replace(/(<\/(h[1-6]|ul|ol|table|tr|blockquote)>)\s*\n+/g, '$1')
  html = html.replace(/(<hr[^>]*>)\s*\n+/g, '$1')
  html = html.replace(/\n\n/g, '<br/><br/>').replace(/\n/g, '<br/>')
  blocks.forEach((block, index) => { html = html.replace(`__BLOCK_PLACEHOLDER_${index}__`, block) })
  // QF-397/398/399/400/401: sanitize final HTML to prevent XSS.
  return DOMPurify.sanitize(html, {
    ADD_ATTR: ['target', 'data-workspace-file', 'data-raw', 'data-chart'],
    ADD_TAGS: ['canvas'],
  })
}
