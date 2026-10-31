"""Non-destructive, repeatable session-sharing upgrade for existing MongoDBs.

Run this from the new chat-api image while the old deployment is still serving.
Only indexes are created; existing documents are never rewritten or deleted.
"""

from __future__ import annotations

from app.dsh_runtime.conversation import ConversationRepository
from app.dsh_runtime.conversation.participants_repository import (
    SessionParticipantsRepository,
)


async def migrate(db) -> None:
    await db.command("ping")
    await ConversationRepository(db).ensure_indexes()
    await SessionParticipantsRepository(db).ensure_indexes()
