export const ASKAI_DSH_HOST_PROTOCOL_VERSION = 'askai.dsh-host.v1'
export const ASKAI_DSH_KERNEL_VERSION = '0.2.0-rc.2'
export const ASKAI_DSH_READY_EVENT = 'askai-dsh-runtime-ready'

export function runtimeHealth(inventory, instanceId = '') {
  return {
    ok: true,
    kernel: 'dsh',
    version: ASKAI_DSH_KERNEL_VERSION,
    protocolVersion: ASKAI_DSH_HOST_PROTOCOL_VERSION,
    instanceId: instanceId || process.env.DSH_INSTANCE_ID || '',
    runtimes: inventory,
  }
}
