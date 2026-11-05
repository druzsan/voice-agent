"""Conversations turn by turn: one complete request, one complete answer."""

import logging
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

import anyio

from voice_agent.conversation.records import (
    CallSetup,
    Conversation,
    EndReason,
    Message,
    NewMessage,
    Source,
)
from voice_agent.conversation.repository import ConversationRepository
from voice_agent.conversation.text import speakable
from voice_agent.llm.prompts import GREETING
from voice_agent.llm.responder import Responder
from voice_agent.speech.audio import read_wav
from voice_agent.speech.ports import (
    AudioClip,
    SpeechRecognizer,
    SpeechSynthesizer,
    Transcript,
)

logger = logging.getLogger(__name__)

# Whisper invents words for noise or silence; such transcripts count as
# "nothing heard" (logged with their metrics, so the thresholds can be tuned)
NO_SPEECH_PROB = 0.6
LOW_LOGPROB = -1.0


class TurnError(Exception):
    """A turn that can't be answered, for a reason the caller should hear."""


class ConversationNotFound(TurnError):
    pass


class ConversationEnded(TurnError):
    pass


class TurnInProgress(TurnError):
    pass


class NoSpeech(TurnError):
    pass


@dataclass(frozen=True)
class Started:
    conversation: Conversation
    greeting: Message
    audio: AudioClip | None


@dataclass(frozen=True)
class TurnResult:
    user_message: Message
    assistant_message: Message
    audio: AudioClip | None


class _Stopwatch:
    def __init__(self) -> None:
        self._start = time.perf_counter()
        self._lap = self._start
        self.timings_ms: dict[str, int] = {}

    def lap(self, stage: str) -> None:
        now = time.perf_counter()
        self.timings_ms[stage] = round((now - self._lap) * 1000)
        self._lap = now

    def total(self) -> dict[str, int]:
        return {
            **self.timings_ms,
            "total": round((time.perf_counter() - self._start) * 1000),
        }


def heard_nothing(transcript: Transcript) -> bool:
    if not transcript.text:
        return True
    return (
        transcript.no_speech_prob is not None
        and transcript.avg_logprob is not None
        and transcript.no_speech_prob > NO_SPEECH_PROB
        and transcript.avg_logprob < LOW_LOGPROB
    )


class TurnService:
    """Starts and ends conversations and answers one turn at a time.

    Turns of one conversation never overlap: a second one while the first
    still runs is refused, and ending waits for the running turn, so the
    stored transcript is complete and in order. The locks live in memory,
    which is enough for the single backend process this app runs as.
    """

    def __init__(
        self,
        repository: ConversationRepository,
        recognizer: SpeechRecognizer,
        synthesizer: SpeechSynthesizer,
        responder: Responder,
        setup: CallSetup,
        history_messages: int,
        max_recording_s: float,
    ) -> None:
        self._repository = repository
        self._recognizer = recognizer
        self._synthesizer = synthesizer
        self._responder = responder
        self._setup = setup
        self._history_messages = history_messages
        self._max_recording_s = max_recording_s
        self._locks: dict[UUID, anyio.Lock] = {}

    async def start(self) -> Started:
        conversation = await self._repository.create_conversation(self._setup)
        greeting = await self._repository.add_message(
            conversation.id,
            NewMessage(role="assistant", source="template", text=GREETING),
        )
        logger.info("Conversation %s started", conversation.id)
        return Started(conversation, greeting, await self._speak(GREETING))

    async def voice_turn(self, conversation_id: UUID, wav: bytes) -> TurnResult:
        samples = read_wav(wav, self._max_recording_s)
        async with self._turn(conversation_id):
            stopwatch = _Stopwatch()
            transcript = await self._recognizer.transcribe(samples)
            stopwatch.lap("stt")
            stt = {
                "audio_ms": transcript.audio_ms,
                "avg_logprob": transcript.avg_logprob,
                "no_speech_prob": transcript.no_speech_prob,
            }
            if heard_nothing(transcript):
                logger.info(
                    "Nothing heard in %s: %r %s", conversation_id, transcript.text, stt
                )
                raise NoSpeech
            return await self._answer(
                conversation_id, transcript.text, "voice", stopwatch, stt=stt
            )

    async def text_turn(
        self, conversation_id: UUID, text: str, via: Literal["keyboard", "keypad"]
    ) -> TurnResult:
        async with self._turn(conversation_id):
            return await self._answer(conversation_id, text, via, _Stopwatch())

    async def end(self, conversation_id: UUID, reason: EndReason) -> None:
        if await self._repository.get_conversation(conversation_id) is None:
            raise ConversationNotFound
        # Wait for a running turn, so its messages are stored before the end
        async with self._lock(conversation_id):
            await self._repository.end_conversation(conversation_id, reason)
        self._locks.pop(conversation_id, None)
        logger.info("Conversation %s ended (%s)", conversation_id, reason)

    def _lock(self, conversation_id: UUID) -> anyio.Lock:
        return self._locks.setdefault(conversation_id, anyio.Lock())

    @asynccontextmanager
    async def _turn(self, conversation_id: UUID) -> AsyncGenerator[None]:
        lock = self._lock(conversation_id)
        try:
            lock.acquire_nowait()
        except anyio.WouldBlock:
            raise TurnInProgress from None
        try:
            conversation = await self._repository.get_conversation(conversation_id)
            if conversation is None:
                raise ConversationNotFound
            if conversation.ended_at is not None:
                raise ConversationEnded
            yield
        finally:
            lock.release()

    async def _answer(
        self,
        conversation_id: UUID,
        text: str,
        source: Source,
        stopwatch: _Stopwatch,
        stt: dict[str, float | int | None] | None = None,
    ) -> TurnResult:
        # History first, so it doesn't contain the new message twice
        history = await self._repository.recent_messages(
            conversation_id, self._history_messages
        )
        user_message = await self._repository.add_message(
            conversation_id,
            NewMessage(
                role="user",
                source=source,
                text=text,
                timings_ms=dict(stopwatch.timings_ms) or None,
                stt=stt,
            ),
        )
        reply = await self._responder.reply(history, text)
        stopwatch.lap("llm")
        audio = await self._speak(reply.text)
        stopwatch.lap("tts")
        assistant_message = await self._repository.add_message(
            conversation_id,
            NewMessage(
                role="assistant",
                source=reply.source,
                text=reply.text,
                timings_ms=stopwatch.total(),
                llm_usage=reply.usage,
            ),
        )
        logger.info("Turn in %s: %s", conversation_id, assistant_message.timings_ms)
        return TurnResult(user_message, assistant_message, audio)

    async def _speak(self, text: str) -> AudioClip | None:
        """The reply as speech; without it the caller can still read the text."""
        try:
            return await self._synthesizer.synthesize(speakable(text))
        except Exception:
            logger.exception("Speech synthesis failed")
            return None
