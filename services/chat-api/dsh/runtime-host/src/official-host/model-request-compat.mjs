function messageText(message) {
  if (typeof message?.content === 'string') return message.content
  if (!Array.isArray(message?.content)) return ''
  return message.content
    .filter(block => block?.type === 'text')
    .map(block => String(block.text ?? ''))
    .join('\n')
}

/** Keep the MOVO Model Gateway request stable when DSH stores system nodes in history. */
export function stableModelRequest(options) {
  const messages = Array.isArray(options.messages) ? options.messages : []
  if (typeof options.system === 'string' && options.system) {
    return { system: options.system, messages }
  }
  const system = messages.findLast(message => message?.role === 'system')
  return {
    system: system === undefined ? options.system : messageText(system),
    messages: system === undefined ? messages : messages.filter(message => message?.role !== 'system'),
  }
}
