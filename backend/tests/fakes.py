"""Stand-ins for the database and the speech models, so tests run without them."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import anyio
import numpy as np

from voice_agent.conversation.records import (
    CallSetup,
    Conversation,
    ConversationDetail,
    ConversationSummary,
    EndReason,
    Message,
    NewMessage,
)
from voice_agent.speech.audio import SAMPLE_RATE, write_wav
from voice_agent.speech.ports import AudioClip, Samples, Transcript
from voice_agent.speech.vad import FRAME_SAMPLES, SpeechProbability


class InMemoryConversationRepository:
    """The conversation storage as plain Python objects.

    Behaves like the PostgreSQL repository where the app relies on it: the
    storage assigns IDs and times, ending twice keeps the first end, and
    lists come newest first.
    """

    def __init__(self) -> None:
        self.conversations: dict[UUID, Conversation] = {}
        self.messages: list[Message] = []
        self.reachable = True

    async def ping(self) -> bool:
        return self.reachable

    async def create_conversation(self, setup: CallSetup) -> Conversation:
        conversation = Conversation(
            **setup.model_dump(),
            id=uuid4(),
            started_at=datetime.now(UTC),
            ended_at=None,
            end_reason=None,
        )
        self.conversations[conversation.id] = conversation
        return conversation

    async def get_conversation(self, conversation_id: UUID) -> Conversation | None:
        return self.conversations.get(conversation_id)

    async def end_conversation(self, conversation_id: UUID, reason: EndReason) -> None:
        conversation = self.conversations.get(conversation_id)
        if conversation is not None and conversation.ended_at is None:
            self.conversations[conversation_id] = conversation.model_copy(
                update={"ended_at": datetime.now(UTC), "end_reason": reason}
            )

    async def add_message(self, conversation_id: UUID, message: NewMessage) -> Message:
        if conversation_id not in self.conversations:
            raise LookupError(f"No conversation {conversation_id}")
        stored = Message(
            **message.model_dump(),
            id=len(self.messages) + 1,
            conversation_id=conversation_id,
            created_at=datetime.now(UTC),
        )
        self.messages.append(stored)
        return stored

    def _messages_of(self, conversation_id: UUID) -> list[Message]:
        return [m for m in self.messages if m.conversation_id == conversation_id]

    async def recent_messages(self, conversation_id: UUID, limit: int) -> list[Message]:
        messages = self._messages_of(conversation_id)
        return messages[-limit:] if limit else []

    async def get_detail(self, conversation_id: UUID) -> ConversationDetail | None:
        conversation = self.conversations.get(conversation_id)
        if conversation is None:
            return None
        return ConversationDetail(
            **conversation.model_dump(), messages=self._messages_of(conversation_id)
        )

    async def list_conversations(self, limit: int) -> list[ConversationSummary]:
        # Insertion order is start order; newest first
        newest = list(reversed(self.conversations.values()))[:limit]
        return [
            ConversationSummary(
                **conversation.model_dump(),
                message_count=len(self._messages_of(conversation.id)),
            )
            for conversation in newest
        ]


def wav_of_silence(seconds: float = 1.0, sample_rate: int = SAMPLE_RATE) -> bytes:
    return write_wav(b"\0\0" * int(seconds * sample_rate), sample_rate)


class FakeRecognizer:
    def __init__(self, text: str = "What time is it?") -> None:
        self.text = text
        self.no_speech_prob = 0.05
        self.avg_logprob = -0.2
        self.heard: list[Samples] = []
        self.trimmed: list[bool] = []
        self.fail = False
        # Set to hold a recognition until the test releases it
        self.release: anyio.Event | None = None

    async def transcribe(
        self, samples: Samples, *, trim_silence: bool = True
    ) -> Transcript:
        self.heard.append(samples)
        self.trimmed.append(trim_silence)
        if self.release is not None:
            await self.release.wait()
        if self.fail:
            raise RuntimeError("recognition failed")
        return Transcript(
            text=self.text,
            audio_ms=round(len(samples) / SAMPLE_RATE * 1000),
            avg_logprob=self.avg_logprob,
            no_speech_prob=self.no_speech_prob,
        )


class FakeSynthesizer:
    def __init__(self) -> None:
        self.spoken: list[str] = []
        self.fail = False

    async def synthesize(self, text: str) -> AudioClip:
        if self.fail:
            raise RuntimeError("synthesis failed")
        self.spoken.append(text)
        return AudioClip(
            wav=wav_of_silence(0.1), sample_rate=SAMPLE_RATE, duration_ms=100
        )


class FakeVad:
    """Loud frames are speech, quiet ones silence."""

    def stream(self) -> SpeechProbability:
        def probability(frame: Samples) -> float:
            return 1.0 if float(np.abs(frame).mean()) > 0.1 else 0.0

        return probability


def pcm(seconds: float, *, loud: bool) -> bytes:
    """Microphone audio for FakeVad: speech when loud, else silence."""
    frames = round(seconds * SAMPLE_RATE / FRAME_SAMPLES)
    sample = 16_000 if loud else 0
    return np.full(frames * FRAME_SAMPLES, sample, dtype="<i2").tobytes()
