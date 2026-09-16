import { createServer } from 'node:http'

export const TEMPORAL_CONTEXT = Object.freeze({
  captured_at_utc: '2026-09-16T00:00:00Z',
  user_local_time: '2026-09-16T08:00:00+08:00',
  user_timezone: 'Asia/Shanghai',
})

export async function waitFor(predicate, message, timeoutMs = 8_000) {
  const started = Date.now()
  while (!predicate()) {
    if (Date.now() - started > timeoutMs) throw new Error(message)
    await new Promise(resolve => setTimeout(resolve, 20))
  }
}

export function sendText(runtime, sessionId, text) {
  return runtime.send({
    sessionId,
    mode: 'prompt',
    content: [{ type: 'text', data: { text } }],
    temporalContext: TEMPORAL_CONTEXT,
  })
}

export function ndjson(response, events) {
  response.writeHead(200, { 'content-type': 'application/x-ndjson' })
  response.end(`${events.map(event => JSON.stringify(event)).join('\n')}\n`)
}

export async function requestBody(request) {
  const chunks = []
  for await (const chunk of request) chunks.push(chunk)
  return JSON.parse(Buffer.concat(chunks).toString('utf8'))
}

export async function withModelServer(handler, run) {
  const server = createServer(handler)
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
  const address = server.address()
  try {
    return await run(`http://127.0.0.1:${address.port}`)
  } finally {
    await new Promise(resolve => server.close(resolve))
  }
}

export function modelProfile(gatewayUrl, additions = {}) {
  return {
    profileVersion: 'runtime-admission-v1',
    modelInstanceId: 'runtime-admission-model',
    modelName: 'runtime-admission-model',
    displayName: 'Runtime admission model',
    gatewayUrl,
    accessToken: 'runtime-admission-token',
    ...additions,
  }
}
