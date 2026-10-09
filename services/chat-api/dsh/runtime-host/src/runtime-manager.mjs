import { randomUUID } from 'node:crypto'
import { KernelRuntime } from './kernel-runtime.mjs'
import { normalizeModelProfile } from './model-profile.mjs'

export class RuntimeManager {
  #runtimes = new Map()
  #isolationOwners = new Map()

  constructor({ storageRoot }) {
    this.storageRoot = storageRoot
  }

  async probe() {
    const runtime = await this.create({
      isolationKey: `startup-probe-${randomUUID()}`,
      profileVersion: 'startup-probe',
    })
    await this.dispose(runtime.runtimeId)
  }

  async create({ isolationKey, profileVersion, modelProfile }) {
    if (this.#isolationOwners.has(isolationKey)) {
      throw new Error(`isolation key already has a runtime: ${isolationKey}`)
    }
    const runtimeId = randomUUID()
    const runtime = new KernelRuntime({
      runtimeId,
      isolationKey,
      profileVersion,
      storageRoot: this.storageRoot,
      modelProfile: normalizeModelProfile(modelProfile, profileVersion),
    })
    // Claim the isolation key *before* the async start so two concurrent
    // creates cannot both pass the check above: the second sees the owner
    // entry and fails fast with "already has a runtime" instead of forking
    // a second kernel for the same isolation key. Roll both registrations
    // back if the start itself fails.
    this.#runtimes.set(runtimeId, runtime)
    this.#isolationOwners.set(isolationKey, runtimeId)
    try {
      await runtime.start()
    } catch (error) {
      this.#runtimes.delete(runtimeId)
      this.#isolationOwners.delete(isolationKey)
      throw error
    }
    return runtime
  }

  get(runtimeId) {
    const runtime = this.#runtimes.get(runtimeId)
    if (runtime === undefined) throw new Error(`runtime not found: ${runtimeId}`)
    return runtime
  }

  // Non-throwing lookup for the cross-replica probes (§12.4): a replica that
  // does not hold the runtime must be able to answer "owned: false" /
  // "seed: null" instead of raising.
  findByRuntimeId(runtimeId) {
    return this.#runtimes.get(runtimeId)
  }

  findByIsolation(isolationKey) {
    const runtimeId = this.#isolationOwners.get(isolationKey)
    return runtimeId === undefined ? undefined : this.#runtimes.get(runtimeId)
  }

  describe(runtime) {
    return {
      runtimeId: runtime.runtimeId,
      isolationKey: runtime.isolationKey,
      profileVersion: runtime.profileVersion,
      modelInstanceId: runtime.modelProfile?.modelInstanceId,
    }
  }

  async exportCompletedSeed(runtimeId, sessionId) {
    return await this.get(runtimeId).exportCompletedSeed(sessionId)
  }

  async dispose(runtimeId) {
    const runtime = this.get(runtimeId)
    this.#runtimes.delete(runtimeId)
    this.#isolationOwners.delete(runtime.isolationKey)
    await runtime.dispose()
  }

  async disposeAll() {
    for (const runtimeId of [...this.#runtimes.keys()]) await this.dispose(runtimeId)
  }

  inventory() {
    return [...this.#runtimes.values()].map(runtime => this.describe(runtime))
  }

  // R1 drain support: aggregate in-flight turns across all runtimes.
  activeSessionCount() {
    let total = 0
    for (const runtime of this.#runtimes.values()) total += runtime.activeSessionCount()
    return total
  }

  async whenSessionsIdle(options) {
    // Poll until every runtime reports zero busy sessions, or the caller's
    // timeout elapses. All runtimes share the same poll interval.
    const deadline = Date.now() + (options?.timeoutMs ?? 60_000)
    while (this.activeSessionCount() > 0) {
      if (Date.now() >= deadline) return false
      await new Promise(resolve => setTimeout(resolve, options?.intervalMs ?? 200))
    }
    return true
  }
}
