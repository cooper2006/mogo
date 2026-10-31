"""Shared MongoDB contract for the per-session message sequence index."""

UNIQUE_MESSAGE_SEQ_INDEX_NAME = "unique_main_session_seq"
MESSAGE_SEQ_INDEX_FILTER = {
    "tenant_id": {"$type": "string"},
    "session_id": {"$type": "objectId"},
    "seq": {"$type": "int"},
}
MESSAGE_SEQ_INDEX_KEYS = [("tenant_id", 1), ("session_id", 1), ("seq", 1)]
