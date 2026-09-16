/** Expand DSH V3's compact assistant stream into MOVO's stable native events. */
export function compatibleSessionEvents(event) {
  if (!['assistant/message', 'assistant/attempt'].includes(event?.type)
      || !Array.isArray(event.data?.stream)) return [event]
  const envelope = { turn: event.data.turn, step: event.data.step }
  const expanded = []
  for (const item of event.data.stream) {
    if (item?.type === 'chunk' && item.chunk !== undefined) {
      expanded.push({ type: 'assistant/chunk', data: { ...envelope, chunk: item.chunk } })
      continue
    }
    if (item?.type !== 'text-chunks' || !Array.isArray(item.texts)) continue
    for (const text of item.texts) {
      expanded.push({
        type: 'assistant/chunk',
        data: { ...envelope, chunk: { type: 'text-delta', index: item.index, text } },
      })
    }
  }
  return [...expanded, event]
}
