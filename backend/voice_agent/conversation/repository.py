from typing import Any, Protocol
from uuid import UUID

from voice_agent.conversation.records import (
    CallSetup,
    Conversation,
    ConversationDetail,
    ConversationSummary,
    EndReason,
    FeedbackRating,
    Message,
    NewMessage,
)


class ConversationRepository(Protocol):
    """Where conversations and their messages are stored.

    The app uses PostgreSQL (voice_agent.db.repository); the tests keep
    everything in memory.
    """

    async def ping(self) -> bool:
        """Whether the storage is reachable."""
        ...

    async def create_conversation(
        self, setup: CallSetup, caller_phone: str | None = None
    ) -> Conversation: ...

    async def get_conversation(self, conversation_id: UUID) -> Conversation | None: ...

    async def end_conversation(self, conversation_id: UUID, reason: EndReason) -> None:
        """Mark the conversation as ended, unless it already is."""
        ...

    async def get_state(self, conversation_id: UUID) -> dict[str, Any] | None:
        """The agent's call state, as last saved."""
        ...

    async def save_state(
        self, conversation_id: UUID, state: dict[str, Any], language: str
    ) -> None: ...

    async def save_feedback(
        self,
        conversation_id: UUID,
        rating: FeedbackRating,
        comment: str | None,
    ) -> Conversation | None:
        """Stores (or replaces) the caller's feedback; None for an unknown call."""
        ...

    async def add_message(
        self, conversation_id: UUID, message: NewMessage
    ) -> Message: ...

    async def recent_messages(self, conversation_id: UUID, limit: int) -> list[Message]:
        """The last `limit` messages, oldest first."""
        ...

    async def get_detail(self, conversation_id: UUID) -> ConversationDetail | None: ...

    async def list_conversations(self, limit: int) -> list[ConversationSummary]:
        """The most recently started conversations first."""
        ...
