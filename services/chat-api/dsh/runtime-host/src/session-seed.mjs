import { createHmac, timingSafeEqual } from 'node:crypto'

/** Resolve a trusted predecessor Session into a native DSH event seed. */
export async function resolveSessionSeed(manager, input, { authToken = '' } = {}) {
  const body = { ...input }
  const hasSealedSeed = Object.hasOwn(body, 'seed')
  if (hasSealedSeed) {
    // Cross-replica path (§12.4 option A): the caller exports a completed
    // seed from the owning replica, seals it there, and ships the sealed
    // payload to the replica that must continue the session. The MAC check
    // below rejects anything not produced by this pool's token, and the
    // source identity is pinned to the MAC so a replayer cannot retarget the
    // seed at a different session.
    const sourceSessionId = String(body.seedSourceSessionId ?? '')
    verifySeededSession(body, authToken)
    delete body.seedSignature
    delete body.seedSourceInstanceId
    delete body.seedSourceSessionId
    if (Object.hasOwn(body, 'parentSessionId')) {
      // Caller supplied it; the MAC already bound it to the source.
    } else {
      // Convenience: the export endpoint's seal shape carries the source
      // session id, so callers can ship the export response verbatim.
      body.parentSessionId = sourceSessionId
    }
    return body
  }
  if (Object.hasOwn(body, 'parentSessionId')) {
    throw new Error('raw Session seed is forbidden over the Runtime Host API')
  }
  const hasSeedRuntime = Object.hasOwn(body, 'seedRuntimeId')
  const hasSeedSession = Object.hasOwn(body, 'seedSessionId')
  if (hasSeedRuntime !== hasSeedSession) {
    throw new Error('seed Runtime and Session identity must be supplied together')
  }
  if (!hasSeedRuntime) return body

  const seedRuntimeId = String(body.seedRuntimeId)
  const seedSessionId = String(body.seedSessionId)
  delete body.seedRuntimeId
  delete body.seedSessionId
  body.seed = await manager.exportCompletedSeed(seedRuntimeId, seedSessionId)
  body.parentSessionId = seedSessionId
  return body
}

// Cross-replica seed (§12.4 option A). ``resolveSessionSeed`` can only see
// runtimes local to this replica, so moving a session to a different replica
// must ship the seed JSON across the wire. Two rules keep that safe:
//
// 1. The seed must have been *produced* by this deployment's own export
//    endpoint, sealed with the shared Runtime Host token -- a request that
//    carries a forged seed fails the MAC check below and is rejected.
// 2. The shape is validated event by event before the seed reaches the kernel,
//    so even a token holder that crafts a payload cannot smuggle in an
//    arbitrary object (the kernel only accepts the shapes in
//    ``liveSessionEvents``).
//
// ``authToken`` is the same bearer token every replica in the pool verifies
// requests with; an attacker who can obtain a valid seed MAC already can
// talk to the whole pool, so signing with it adds no escalation.

export function seedMac(authToken, sourceInstanceId, sourceSessionId, seed) {
  const payload = JSON.stringify([sourceInstanceId, sourceSessionId, seed])
  return createHmac('sha256', authToken).update(payload, 'utf8').digest('base64')
}

export function verifySeededSession(body, authToken) {
  if (!Object.hasOwn(body, 'seed') || !Array.isArray(body.seed)) {
    throw new Error('seedSessionId and seedSignature must be supplied together')
  }
  for (const event of body.seed) assertSeedEvent(event)
  if (typeof body.seedSignature !== 'string' || !authToken || authToken.length < 32) {
    throw new Error('seedSignature requires a Runtime Host authentication token')
  }
  const sourceInstanceId = String(body.seedSourceInstanceId ?? '')
  const sourceSessionId = String(body.seedSourceSessionId ?? '')
  const expected = seedMac(authToken, sourceInstanceId, sourceSessionId, body.seed)
  const actual = Buffer.from(body.seedSignature, 'utf8')
  const target = Buffer.from(expected, 'utf8')
  if (actual.length !== target.length || !timingSafeEqual(actual, target)) {
    throw new Error('seedSignature does not match this pool authentication token')
  }
}

function assertSeedEvent(event) {
  if (typeof event !== 'object' || event === null || Array.isArray(event)) {
    throw new Error('seed events must be plain objects')
  }
  if (typeof event.type !== 'string' || !event.type) {
    throw new Error('seed events must carry a string type')
  }
}

// The export endpoint ships this sealed shape; create_session accepts the same
// shape, minus seedSignature which it re-verifies with the pool token.
export function sealSeed(authToken, sourceInstanceId, sourceSessionId, seed) {
  return {
    seed,
    seedSignature: seedMac(authToken, sourceInstanceId, sourceSessionId, seed),
    seedSourceInstanceId: sourceInstanceId,
    seedSourceSessionId: sourceSessionId,
    parentSessionId: sourceSessionId,
  }
}
