/**
 * Buffer the request body once.
 *
 * A request stream can only be read once, but the cross-replica hand-off and
 * the local handler may both need the body. Buffering it up front lets either
 * path consume it without the other starving.
 */
export async function readBody(request) {
  if (Buffer.isBuffer(request._bufferedBody)) return request._bufferedBody
  const chunks = []
  for await (const chunk of request) chunks.push(chunk)
  return chunks.length === 0 ? Buffer.alloc(0) : Buffer.concat(chunks)
}

export async function readJson(request) {
  const body = await readBody(request)
  if (body.length === 0) return {}
  return JSON.parse(body.toString('utf8'))
}

export function sendJson(response, status, value) {
  const body = JSON.stringify(value)
  response.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'content-length': Buffer.byteLength(body),
  })
  response.end(body)
}

export function routeParts(request) {
  const url = new URL(request.url, 'http://runtime-host.local')
  return { parts: url.pathname.split('/').filter(Boolean), query: url.searchParams }
}
