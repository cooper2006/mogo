export const inject = ['tools']
export const name = 'mogo-dsh-test-bundle'

export function apply(ctx) {
  ctx.provide('mogoDshTestBundle', { ready: true })
  ctx.tools.register({
    name: 'mogo_plugin_smoke',
    description: 'Return a deterministic plugin execution marker.',
    parameters: { type: 'object', properties: {}, additionalProperties: false },
    output: {
      schema: { type: 'object', properties: { marker: { type: 'string' } }, required: ['marker'] },
      render: (_args, value) => [{ type: 'text', text: value.marker }],
    },
    execute: async () => ({ marker: 'MOGO_PLUGIN_EXECUTED' }),
  })
}
