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
const nonAscii = /[^\x20-\x7e]/
const failures = []
const missingByApp = new Map()

function files(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap(entry => {
    const file = path.join(dir, entry.name)
    return entry.isDirectory() ? files(file) : [file]
  })
}

for (const app of ['admin-web', 'user-web']) {
  const sourceRoot = path.join(root, 'apps', app, 'src')
  const sourceFiles = files(sourceRoot).filter(file => /\.(ts|tsx|vue)$/.test(file))
  const catalogKeys = new Set()

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
            if (nonAscii.test(key)) failures.push(`${path.relative(root, file)}: non-ASCII catalog key ${JSON.stringify(key)}`)
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
      const template = source.split(/<script\b/i, 1)[0].replace(/<!--[\s\S]*?-->/g, '')
      for (const match of template.matchAll(/(?:^|[\s<])(?:aria-label|title|placeholder)="([^"]*)"/gm)) {
        if (/[\u3400-\u9fff]/u.test(match[1])) failures.push(`${path.relative(root, file)}: hard-coded Chinese template attribute ${JSON.stringify(match[1])}`)
      }
      for (const match of template.matchAll(/>\s*([^<{]*[\u3400-\u9fff][^<{]*)\s*</gu)) {
        failures.push(`${path.relative(root, file)}: hard-coded Chinese template text ${JSON.stringify(match[1].trim())}`)
      }
    }
    const calls = /\bt\(\s*(['"`])((?:\\.|(?!\1)[\s\S])*?)\1/g
    let match
    while ((match = calls.exec(source))) {
      const key = match[2]
      const line = source.slice(0, match.index).split('\n').length
      if (nonAscii.test(key)) failures.push(`${path.relative(root, file)}:${line}: non-ASCII t() key ${JSON.stringify(key)}`)
      else if (!key.includes('${') && !/^\s*\+/.test(source.slice(calls.lastIndex)) && !catalogKeys.has(key)) {
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
  for (const [app, byKey] of missingByApp) {
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
  console.log('')
}

if (failures.length) {
  console.error(failures.join('\n'))
  process.exitCode = 1
} else {
  console.log('Admin and user web locale keys and static t() calls are valid.')
}
