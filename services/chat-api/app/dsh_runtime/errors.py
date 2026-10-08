"""Explicit failure types for the DSH kernel boundary."""


class DshRuntimeError(RuntimeError):
    """Base error for a failed DSH host or request."""


class DshTransportError(DshRuntimeError):
    """The Runtime Host could not be reached or returned an invalid response."""


class DshProtocolError(DshRuntimeError):
    """The Runtime Host violated the pinned AgentKernel protocol."""


class DshNotFoundError(DshRuntimeError):
    """The requested ASKAI-owned runtime/session binding does not exist."""


class DshAffinityError(DshNotFoundError):
    """The runtime/session exists in ASKAI state but the addressed host does not own it.

    This is an affinity/routing failure: the request reached a Runtime Host
    replica that does not hold the requested runtime (for example a chat-api
    restart degraded sticky routing to the runtime id, or the upstream LB
    rehashed the session). It is a subclass of ``DshNotFoundError`` so existing
    not-found handling still applies, while callers that can recover (re-resolve,
    re-discover, or surface "session is not live") can detect it explicitly.
    """
