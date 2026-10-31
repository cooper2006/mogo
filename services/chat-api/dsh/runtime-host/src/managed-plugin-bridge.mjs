// The DSH manager owns package installation, compatibility checks, profile
// locking and rollback. The MOGO Host only exposes its operations to its
// authenticated control plane; it never runs pnpm or imports user specs here.
export class ManagedPluginBridge {
  constructor(ctx) {
    const manager = ctx.get('pluginManager')
    if (manager === undefined) throw new Error('managed DSH plugin profile is unavailable')
    this.manager = manager
  }

  async list() {
    return { bundles: await this.manager.listBundles() }
  }

  async inspect(spec, registry) {
    return await this.manager.inspect(spec, registry ? { registry } : undefined)
  }

  async install(spec, { registry, requestId } = {}) {
    return await this.manager.installBundle(spec, {
      enabled: false,
      ...(registry ? { registry } : {}),
      ...(requestId ? { requestId } : {}),
    })
  }

  async enable(name, enabled) {
    return await this.manager.setBundleEnabled(name, enabled)
  }

  async remove(name) {
    return await this.manager.removeBundle(name)
  }
}
