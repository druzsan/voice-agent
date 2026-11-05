from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, text, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

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
from voice_agent.db.models import ConversationRow, MessageRow


def create_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(database_url, pool_pre_ping=True)


def _conversation(row: ConversationRow) -> Conversation:
    return Conversation.model_validate(row, from_attributes=True)


def _message(row: MessageRow) -> Message:
    return Message.model_validate(row, from_attributes=True)


class SqlConversationRepository:
    """Stores conversations and their messages in PostgreSQL, one transaction per call.

    Returns immutable records, never ORM objects, so nothing loads lazily
    outside a session.
    """

    def __init__(self, engine: AsyncEngine) -> None:
        self._sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def ping(self) -> bool:
        try:
            async with self._sessions() as session:
                await session.execute(text("SELECT 1"))
        except (SQLAlchemyError, OSError):
            return False
        return True

    async def create_conversation(
        self, setup: CallSetup, caller_phone: str | None = None
    ) -> Conversation:
        async with self._sessions.begin() as session:
            row = ConversationRow(**setup.model_dump(), caller_phone=caller_phone)
            session.add(row)
            await session.flush()
            await session.refresh(row)
            return _conversation(row)

    async def get_conversation(self, conversation_id: UUID) -> Conversation | None:
        async with self._sessions() as session:
            row = await session.get(ConversationRow, conversation_id)
            return _conversation(row) if row else None

    async def end_conversation(self, conversation_id: UUID, reason: EndReason) -> None:
        """Mark the conversation as ended, unless it already is."""
        async with self._sessions.begin() as session:
            await session.execute(
                update(ConversationRow)
                .where(
                    ConversationRow.id == conversation_id,
                    ConversationRow.ended_at.is_(None),
                )
                .values(ended_at=func.now(), end_reason=reason)
            )

    async def get_state(self, conversation_id: UUID) -> dict[str, Any] | None:
        async with self._sessions() as session:
            return await session.scalar(
                select(ConversationRow.state).where(
                    ConversationRow.id == conversation_id
                )
            )

    async def save_state(
        self, conversation_id: UUID, state: dict[str, Any], language: str
    ) -> None:
        async with self._sessions.begin() as session:
            await session.execute(
                update(ConversationRow)
                .where(ConversationRow.id == conversation_id)
                .values(state=state, language=language)
            )

    async def save_feedback(
        self,
        conversation_id: UUID,
        rating: FeedbackRating,
        comment: str | None,
    ) -> Conversation | None:
        async with self._sessions.begin() as session:
            row = await session.get(ConversationRow, conversation_id)
            if row is None:
                return None
            row.feedback_rating = rating
            row.feedback_comment = comment
            row.feedback_at = datetime.now(UTC)
            await session.flush()
            return _conversation(row)

    async def add_message(self, conversation_id: UUID, message: NewMessage) -> Message:
        async with self._sessions.begin() as session:
            row = MessageRow(conversation_id=conversation_id, **message.model_dump())
            session.add(row)
            await session.flush()
            await session.refresh(row)
            return _message(row)

    async def recent_messages(self, conversation_id: UUID, limit: int) -> list[Message]:
        """The last `limit` messages, oldest first."""
        async with self._sessions() as session:
            rows = await session.scalars(
                select(MessageRow)
                .where(MessageRow.conversation_id == conversation_id)
                .order_by(MessageRow.id.desc())
                .limit(limit)
            )
            return [_message(row) for row in reversed(rows.all())]

    async def get_detail(self, conversation_id: UUID) -> ConversationDetail | None:
        async with self._sessions() as session:
            conversation = await session.get(ConversationRow, conversation_id)
            if conversation is None:
                return None
            rows = await session.scalars(
                select(MessageRow)
                .where(MessageRow.conversation_id == conversation_id)
                .order_by(MessageRow.id)
            )
            return ConversationDetail(
                **_conversation(conversation).model_dump(),
                messages=[_message(row) for row in rows],
            )

    async def list_conversations(self, limit: int) -> list[ConversationSummary]:
        """The most recently started conversations first."""
        message_count = (
            select(func.count(MessageRow.id))
            .where(MessageRow.conversation_id == ConversationRow.id)
            .scalar_subquery()
        )
        async with self._sessions() as session:
            result = await session.execute(
                select(ConversationRow, message_count)
                .order_by(ConversationRow.started_at.desc(), ConversationRow.id.desc())
                .limit(limit)
            )
            return [
                ConversationSummary(
                    **_conversation(row).model_dump(), message_count=count
                )
                for row, count in result
            ]
