#!/usr/bin/env node
const fs = require('node:fs')
const path = require('node:path')

// The catalogue is parsed with the TypeScript AST on purpose: locale values
// may contain braces (e.g. "{capabilities}；{tools}"), so a regex cannot
// tell an entry body from a nested object and would silently drop keys.
function loadTypeScript() {
  const candidates = [
    process.env.I18N_TYPESCRIPT_PATH,
    path.join(__dirname, '../apps/admin-web/node_modules/typescript'),
    path.join(__dirname, '../node_modules/typescript'),
  ].filter(Boolean)
  for (const candidate of candidates) {
    try {
      return require(candidate)
    } catch (error) {
      if (error.code !== 'MODULE_NOT_FOUND') throw error
    }
  }
  console.error(
    'The TypeScript parser is required to read the locale catalogues.\n' +
      'Install it first:\n\n' +
      '  npm --prefix apps/admin-web install --no-save typescript@5.6.3\n\n' +
      'Or point I18N_TYPESCRIPT_PATH at an existing installation.',
  )
  process.exit(2)
}

const ts = loadTypeScript()
const listMissing = process.argv.includes('--list')

const root = path.resolve(__dirname, '..')
const failures = []
const missingByApp = new Map()

function files(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap(entry => {
    const file = path.join(dir, entry.name)
    return entry.isDirectory() ? files(file) : [file]
  })
}

// A template that calls t() without binding t in <script setup> compiles to
// `_ctx.t(...)`, which is undefined at runtime and crashes the whole app with
// "c.t is not a function". Detect the missing binding before it reaches a build.
function hasTBinding(script) {
  const patterns = [
    /import\s*\{[^}]*\bt\b[^}]*\}\s*from\s*['"][^'"]*i18n['"]/, // import { t } from '@/composables/i18n'
    /\b(?:const|let|var)\s*\{[^}]*\bt\b[^}]*\}\s*=/, // const { t } = useI18n()
    /\b(?:const|let|var)\s+t\s*=/,
    /\bfunction\s+t\s*\(/,
    /\bt\s*:\s*[^,}]+/, // returned from setup(): { t, ... }
  ]
  return patterns.some(pattern => pattern.test(script))
}

for (const app of ['admin-web', 'user-web']) {
  const sourceRoot = path.join(root, 'apps', app, 'src')
  const sourceFiles = files(sourceRoot).filter(file => /\.(ts|tsx|vue)$/.test(file))
  const catalogKeys = new Set()

  // A locale module that is never spread into messages.ts is invisible at
  // runtime: t() falls back to returning the raw key. The catalogue scan below
  // would still see its keys, so this wiring check must run separately.
  const aggregator = path.join(sourceRoot, 'locales', 'messages.ts')
  const aggregatorSource = fs.readFileSync(aggregator, 'utf8')
  for (const file of sourceFiles.filter(f => f.includes(`${path.sep}locales${path.sep}`) && f.endsWith('.ts') && f !== aggregator)) {
    const source = fs.readFileSync(file, 'utf8')
    const tree = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true)
    let isLocaleModule = false
    for (const statement of tree.statements) {
      if (!ts.isVariableStatement(statement) || !statement.modifiers?.some(m => m.kind === ts.SyntaxKind.ExportKeyword)) continue
      for (const declaration of statement.declarationList.declarations) {
        let initializer = declaration.initializer
        while (initializer && (ts.isAsExpression(initializer) || ts.isSatisfiesExpression(initializer) || ts.isParenthesizedExpression(initializer))) initializer = initializer.expression
        if (!initializer || !ts.isObjectLiteralExpression(initializer) || !initializer.properties.length) continue
        let localeShaped = 0
        for (const property of initializer.properties) {
          if (!ts.isPropertyAssignment(property) || !ts.isObjectLiteralExpression(property.initializer)) continue
          const fields = new Set(property.initializer.properties.map(p => p.name?.getText(tree).replace(/^['"]|['"]$/g, '')))
          if (fields.has('zh') || fields.has('zh-CN') || fields.has('en') || fields.has('en-US')) localeShaped++
        }
        if (localeShaped > 0 && localeShaped >= initializer.properties.length * 0.5) isLocaleModule = true
      }
    }
    if (!isLocaleModule) continue
    const stem = path.basename(file, '.ts')
    const imported = new RegExp(`from\\s+['\"][^'\"]*${stem.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}['\"]`).test(aggregatorSource)
    if (!imported) failures.push(`${path.relative(root, file)}: locale module is never imported by locales/messages.ts`)
  }

  for (const file of sourceFiles.filter(file => file.includes(`${path.sep}locales${path.sep}`) && file.endsWith('.ts'))) {
    const source = fs.readFileSync(file, 'utf8')
    const tree = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true)
    function visit(node) {
      if (ts.isPropertyAssignment(node) && ts.isStringLiteral(node.name)) {
        const key = node.name.text
        // Locale entries are objects with a language-specific translation.
        if (ts.isObjectLiteralExpression(node.initializer)) {
          const fields = new Set(node.initializer.properties.map(property => property.name?.getText(tree).replace(/^['"]|['"]$/g, '')))
          if (fields.has('zh') || fields.has('zh-CN')) {
            // 用中文原文作 key 是本项目既定风格（3000+ 条目），不是错误。
            // 真正需要守卫的是「有没有配英文」以及「t() 的 key 能否命中」。
            catalogKeys.add(key)
            if (!fields.has(app === 'admin-web' ? 'en-US' : 'en')) {
              failures.push(`${path.relative(root, file)}: missing English translation for ${JSON.stringify(key)}`)
            }
          }
        }
      }
      ts.forEachChild(node, visit)
    }
    visit(tree)
  }

  for (const file of sourceFiles) {
    const source = fs.readFileSync(file, 'utf8')
    if (file.endsWith('.vue')) {
      // Blank out the script blocks but keep the line count, so reported line
      // numbers still match the original file.
      const scriptBlocks = []
      const template = source.replace(/<script\b[\s\S]*?<\/script>/gi, block => {
        scriptBlocks.push(block)
        return block.replace(/[^\n]/g, '')
      })
      for (const match of template.matchAll(/(?:^|[\s<])(?:aria-label|title|placeholder)="([^"]*)"/gm)) {
        if (/[\u3400-\u9fff]/u.test(match[1])) failures.push(`${path.relative(root, file)}: hard-coded Chinese template attribute ${JSON.stringify(match[1])}`)
      }
      for (const match of template.matchAll(/>\s*([^<{]*[\u3400-\u9fff][^<{]*)\s*</gu)) {
        failures.push(`${path.relative(root, file)}: hard-coded Chinese template text ${JSON.stringify(match[1].trim())}`)
      }
      const tCall = /(?<![\w$.])t\s*\(/.exec(template)
      if (tCall && !hasTBinding(scriptBlocks.join('\n'))) {
        const line = template.slice(0, tCall.index).split('\n').length
        failures.push(`${path.relative(root, file)}:${line}: template calls t() but the component never binds t`)
      }
    }
    const calls = /\bt\(\s*(['"`])((?:\\.|(?!\1)[\s\S])*?)\1/g
    let match
    while ((match = calls.exec(source))) {
      // 字符串字面量中的转义序列要还原成运行时值，才能与 catalog 的 key
      // （TS AST 读出的也是运行时值）正确比对。
      const key = match[2]
        .replace(/\\n/g, '\n')
        .replace(/\\t/g, '\t')
        .replace(/\\(['"`\\])/g, '$1')
      const line = source.slice(0, match.index).split('\n').length
      // 中文 key 同样要校验 catalog：过去 non-ASCII 分支会直接跳过，
      // 让 752 个「中文界面回显原文看似正常、英文界面漏翻译」的 key
      // 长期潜伏。现在所有 key 走同一条校验路径。
      if (!key.includes('${') && !/^\s*\+/.test(source.slice(calls.lastIndex)) && !catalogKeys.has(key)) {
        failures.push(`${path.relative(root, file)}:${line}: missing translation for ${JSON.stringify(key)}`)
        if (!missingByApp.has(app)) missingByApp.set(app, new Map())
        const byKey = missingByApp.get(app)
        if (!byKey.has(key)) byKey.set(key, [])
        byKey.get(key).push(`${path.relative(root, file)}:${line}`)
      }
    }
  }
}

if (listMissing) {
  const allMissing = new Set()
  for (const [app, byKey] of missingByApp) {
    for (const key of byKey.keys()) allMissing.add(key)
    const namespaces = new Map()
    for (const [key, locations] of byKey) {
      const namespace = key.split('.')[0]
      if (!namespaces.has(namespace)) namespaces.set(namespace, [])
      namespaces.get(namespace).push({ key, locations })
    }
    console.log(`\n===== ${app} — ${byKey.size} missing keys =====`)
    for (const [namespace, entries] of [...namespaces.entries()].sort((a, b) => b[1].length - a[1].length)) {
      console.log(`\n### ${namespace} (${entries.length})`)
      for (const entry of entries) {
        console.log(`  ${entry.key}   [${entry.locations.length}x ${entry.locations[0]}]`)
      }
    }
  }
  // Machine-readable dump for bulk backfilling translations; keeps the exact
  // runtime key (including embedded newlines) instead of a lossy text parse.
  if (process.env.I18N_DUMP_MISSING) {
    fs.writeFileSync(process.env.I18N_DUMP_MISSING, JSON.stringify([...allMissing], null, 1))
  }
  console.log('')
}

if (failures.length) {
  console.error(failures.join('\n'))
  process.exitCode = 1
} else {
  console.log('Admin and user web locale keys and static t() calls are valid.')
}
