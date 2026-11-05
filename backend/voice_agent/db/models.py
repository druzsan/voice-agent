from datetime import datetime
from typing import Any, get_args
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Identity,
    Index,
    Text,
    false,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from voice_agent.conversation.records import EndReason, FeedbackRating, Role, Source
from voice_agent.db.base import Base


def _one_of(column: str, values: tuple[str, ...]) -> str:
    listed = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({listed})"


class ConversationRow(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        CheckConstraint(_one_of("end_reason", get_args(EndReason)), name="end_reason"),
        CheckConstraint(
            _one_of("feedback_rating", get_args(FeedbackRating)),
            name="feedback_rating",
        ),
    )

    # Time-ordered UUIDs (built into PostgreSQL 18)
    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=text("uuidv7()"))
    started_at: Mapped[datetime] = mapped_column(server_default=func.now())
    ended_at: Mapped[datetime | None]
    end_reason: Mapped[str | None] = mapped_column(Text)
    # Configuration the conversation ran with
    llm_provider: Mapped[str] = mapped_column(Text)
    llm_model: Mapped[str | None] = mapped_column(Text)
    stt_model: Mapped[str] = mapped_column(Text)
    tts_voice: Mapped[str] = mapped_column(Text)
    # The caller's number as the phone line reports it (E.164)
    caller_phone: Mapped[str | None] = mapped_column(Text)
    # The language the conversation is held in now (en, de)
    language: Mapped[str | None] = mapped_column(Text)
    # The agent's call state (voice_agent.agent.state.CallState)
    state: Mapped[dict[str, Any] | None]
    # The caller's feedback on the call: up or down, and an optional comment
    feedback_rating: Mapped[str | None] = mapped_column(Text)
    feedback_comment: Mapped[str | None] = mapped_column(Text)
    feedback_at: Mapped[datetime | None]


class MessageRow(Base):
    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint(_one_of("role", get_args(Role)), name="role"),
        CheckConstraint(_one_of("source", get_args(Source)), name="source"),
        Index("ix_messages_conversation_id_id", "conversation_id", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE")
    )
    role: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    timings_ms: Mapped[dict[str, int] | None]
    stt: Mapped[dict[str, Any] | None]
    llm_usage: Mapped[dict[str, int] | None]
    # Time, tokens, audio and cost per service and model (voice_agent.usage)
    usage: Mapped[list[dict[str, Any]] | None]
    interrupted: Mapped[bool] = mapped_column(Boolean, server_default=false())
    heard_text: Mapped[str | None] = mapped_column(Text)
    # The model's messages of the turn, tool calls and results included
    # (PydanticAI's JSON), replayed as the conversation history
    model_messages: Mapped[list[dict[str, Any]] | None]
    # The turn's tool calls, for the transcript: name, result status, label
    tool_calls: Mapped[list[dict[str, Any]] | None]
