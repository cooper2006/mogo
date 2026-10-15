/**
 * Session-level trajectory aggregation (028, route C).
 *
 * The conversation and the trajectory are two projections of the SAME V3 event
 * stream (see services/chat-api/app/dsh_runtime/events/projection.py). This
 * module owns the pure part of the trajectory view — picking the assistant
 * rounds out of a session's message list — so it stays unit-testable without
 * mounting a component.
 */

export type TrajectorySourceMessage = {
  _id?: string
  role?: string
}

export type TrajectoryRoundRef<TMessage extends TrajectorySourceMessage> = {
  key: string
  /** 1-based round index within the session (assistant turns only). */
  index: number
  message: TMessage
}

/**
 * Collect the assistant rounds of a session in chronological order.
 * Non-assistant messages are skipped; rounds without an id get a stable
 * positional key so the trajectory view never reuses a Vue key.
 */
export function collectTrajectoryRounds<TMessage extends TrajectorySourceMessage>(
  messages: readonly TMessage[] | undefined,
): TrajectoryRoundRef<TMessage>[] {
  const rounds: TrajectoryRoundRef<TMessage>[] = []
  let index = 0
  for (const message of messages || []) {
    if (message.role !== 'assistant') continue
    index += 1
    rounds.push({
      key: message._id || `trajectory_round_${index}`,
      index,
      message,
    })
  }
  return rounds
}
