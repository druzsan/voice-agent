"""A live call over one connection: hands-free turns, streamed replies, barge-in.

The session is the only one that decides the call's state:

    connect → speaking (greeting) → listening
    listening ─(utterance ends | text)→ thinking ─(first clip)→ speaking
    speaking ─(last clip played | clips' length + grace)→ listening
    speaking ─(caller speech ≥ barge_in_ms)→ interrupted → listening
    any ─(hangup | disconnect | max call time | fatal error)→ ended

With live recognition, the caller's audio goes to the recognizer while
they speak, and the utterance is committed when the pause ends it; if that
fails, the recording is transcribed as a whole. Replies are spoken sentence
by sentence, each sent to the browser in pieces as it's synthesized.

Each reply is stored once it's over: played to the end, or interrupted
(with what the caller heard of it). A single backend process is assumed:
the state lives in memory, per connection.
"""

import base64
import logging
import math
import time
from collections import deque
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Literal, Protocol
from uuid import UUID

import anyio
import numpy as np
from anyio.lowlevel import checkpoint_if_cancelled

from voice_agent.conversation.protocol import (
    AssistantDelta,
    AssistantMessage,
    AudioEnd,
    AudioFrame,
    AudioPiece,
    CallEnded,
    CallError,
    CallerSpeech,
    CallStarted,
    CallState,
    ClientEvent,
    Hangup,
    Interrupted,
    Mute,
    Played,
    ServerMessage,
    StateChanged,
    TextInput,
    TurnDone,
    UserMessage,
)
from voice_agent.conversation.records import (
    CallSetup,
    EndReason,
    Message,
    NewMessage,
    Source,
)
from voice_agent.conversation.repository import ConversationRepository
from voice_agent.conversation.text import SentenceBuffer, speakable
from voice_agent.conversation.turns import heard_nothing
from voice_agent.llm.prompts import GREETING, LLM_FAILED
from voice_agent.llm.responder import Responder, StreamedReply
from voice_agent.speech.audio import SAMPLE_RATE
from voice_agent.speech.ports import (
    AudioChunk,
    LiveRecognizer,
    LiveTranscription,
    PendingTranscript,
    Samples,
    SpeechRecognizer,
    SpeechSynthesizer,
    Transcript,
)
from voice_agent.speech.vad import (
    Endpointer,
    EndpointerSettings,
    SpeechAudio,
    SpeechEnded,
    SpeechStarted,
    VoiceActivityDetector,
)

logger = logging.getLogger(__name__)


class Disconnected(Exception):
    """The connection is gone; `reason` is how the call ends."""

    def __init__(self, reason: EndReason = "disconnect") -> None:
        super().__init__(reason)
        self.reason: EndReason = reason


class CallTransport(Protocol):
    """The connection to the browser (a WebSocket in the app)."""

    async def receive(self) -> ClientEvent:
        """The next message; raises Disconnected when the connection is gone."""
        ...

    async def send(self, message: ServerMessage) -> None:
        """Sends a message; does nothing once the connection is gone."""
        ...


@dataclass(frozen=True)
class CallSettings:
    history_messages: int
    max_call_s: float
    # Speech that interrupts a reply; shorter sounds ("mhm", coughs, echo)
    # don't
    barge_in_ms: int
    endpointer: EndpointerSettings
    # A lost `played` message can't hold the call: playback counts as over
    # this long after the clips should have ended
    playback_grace_s: float = 1.5
    # Typed messages waiting while a turn runs
    max_queued: int = 3


# Caller input waiting for its turn
@dataclass(frozen=True)
class _Greeting:
    pass


@dataclass(frozen=True)
class _Spoken:
    audio: Samples = field(repr=False)
    # When the caller stopped talking (time.perf_counter)
    ended_at: float
    # Its parts' transcripts from live recognition, if that is in use
    pending: tuple[PendingTranscript, ...] = ()


@dataclass(frozen=True)
class _Typed:
    text: str
    via: Literal["keyboard", "keypad"]
    received_at: float


_Input = _Greeting | _Spoken | _Typed

# Between two utterances that are answered together
_JOIN_SILENCE = np.zeros(SAMPLE_RATE // 4, dtype=np.float32)


@dataclass
class _Reply:
    """One assistant message in the making."""

    turn: int
    source: Source
    # When the caller finished their message (time.perf_counter)
    started: float
    text: str = ""
    # The clips sent for it: number and text
    spoken: list[tuple[int, str]] = field(default_factory=list[tuple[int, str]])
    usage: dict[str, int] | None = None
    timings_ms: dict[str, int] = field(default_factory=dict[str, int])
    # Played to the end
    finished: bool = False
    # The model failed partway; nothing is known about what was heard
    failed: bool = False
    stored: bool = False

    def since_start_ms(self) -> int:
        return round((time.perf_counter() - self.started) * 1000)


class _Playback:
    """The clips the browser still has to play."""

    def __init__(self, grace_s: float) -> None:
        self._grace_s = grace_s
        self._outstanding: set[int] = set()
        self._estimated_end = 0.0
        self._changed = anyio.Event()
        self.played: set[int] = set()

    def sent(self, clip: int, duration_ms: float) -> None:
        """More audio of the clip; the browser plays it all one after the other."""
        now = anyio.current_time()
        self._estimated_end = max(self._estimated_end, now) + duration_ms / 1000
        self._outstanding.add(clip)

    def played_clip(self, clip: int) -> None:
        self.played.add(clip)
        self._outstanding.discard(clip)
        self._changed.set()

    def drop(self) -> None:
        """The browser dropped its queued clips."""
        self._outstanding.clear()
        self._estimated_end = 0.0
        self._changed.set()

    async def wait(self) -> None:
        """Until every clip sent so far has played, or should have long ago."""
        while self._outstanding:
            remaining = self._estimated_end + self._grace_s - anyio.current_time()
            if remaining <= 0:
                logger.warning("No played message for clips %s", self._outstanding)
                self._outstanding.clear()
                return
            self._changed = anyio.Event()
            with anyio.move_on_after(remaining):
                await self._changed.wait()


class CallSession:
    """One phone call: listens, answers, speaks, and stores the conversation."""

    def __init__(
        self,
        *,
        transport: CallTransport,
        repository: ConversationRepository,
        recognizer: SpeechRecognizer,
        synthesizer: SpeechSynthesizer,
        responder: Responder,
        vad: VoiceActivityDetector,
        setup: CallSetup,
        settings: CallSettings,
        live_recognizer: LiveRecognizer | None = None,
    ) -> None:
        self._transport = transport
        self._repository = repository
        self._recognizer = recognizer
        self._live_recognizer = live_recognizer
        # Set while the call runs, when live recognition is in use
        self._live: LiveTranscription | None = None
        self._synthesizer = synthesizer
        self._responder = responder
        self._setup = setup
        self._settings = settings
        self._endpointer = Endpointer(vad.stream(), settings.endpointer)
        self._conversation_id: UUID | None = None
        self._state: CallState | None = None
        self._muted = False
        self._pending: deque[_Input] = deque()
        self._input_ready = anyio.Event()
        self._turn = 0
        self._clip = 0
        self._turn_scope: anyio.CancelScope | None = None
        self._reply: _Reply | None = None
        self._playback = _Playback(settings.playback_grace_s)

    async def start(self) -> None:
        """Creates the conversation; raises when the storage isn't available."""
        conversation = await self._repository.create_conversation(self._setup)
        self._conversation_id = conversation.id
        logger.info("Call %s started", conversation.id)
        await self._send(CallStarted(conversation_id=conversation.id))

    async def run(self) -> EndReason:
        """The call, from the greeting until it ends; returns why it ended."""
        conversation_id = self._conversation_id
        assert conversation_id is not None, "start() first"
        reason: EndReason = "error"
        try:
            # Connects while the greeting plays
            async with self._live_session() as live:
                self._live = live
                async with anyio.create_task_group() as tasks:
                    tasks.start_soon(self._take_turns)
                    await self._queue(_Greeting())
                    with anyio.move_on_after(self._settings.max_call_s) as deadline:
                        reason = await self._listen()
                    if deadline.cancelled_caught:
                        reason = "timeout"
                    # Interrupts a running turn; it stores what it has
                    tasks.cancel_scope.cancel()
        except Exception:
            logger.exception("Call %s failed", conversation_id)
            reason = "error"
        finally:
            with anyio.CancelScope(shield=True):
                try:
                    await self._repository.end_conversation(conversation_id, reason)
                except Exception:
                    logger.exception("Couldn't store the end of %s", conversation_id)
                await self._send(CallEnded(reason=reason))
        logger.info("Call %s ended (%s)", conversation_id, reason)
        return reason

    @asynccontextmanager
    async def _live_session(self) -> AsyncGenerator[LiveTranscription | None]:
        if self._live_recognizer is None:
            yield None
            return
        async with self._live_recognizer.open() as live:
            try:
                yield live
            finally:
                self._live = None

    # --- Caller input ----------------------------------------------------------

    async def _listen(self) -> EndReason:
        while True:
            try:
                event = await self._transport.receive()
            except Disconnected as gone:
                return gone.reason
            match event:
                case AudioFrame(pcm=pcm):
                    await self._hear(pcm)
                case TextInput(text=text, via=via):
                    await self._queue(_Typed(text, via, time.perf_counter()))
                case Played(clip=clip):
                    self._playback.played_clip(clip)
                case Mute(muted=muted):
                    await self._mute(muted)
                case Hangup():
                    return "hangup"

    async def _hear(self, pcm: bytes) -> None:
        if self._muted:
            return
        # Scoring a 32 ms frame takes well under a millisecond, so it runs
        # right here instead of in a worker thread
        for event in self._endpointer.feed(pcm):
            match event:
                case SpeechStarted():
                    await self._send(CallerSpeech(active=True))
                case SpeechAudio(audio=audio):
                    if self._live is not None:
                        await self._live.append(audio)
                case SpeechEnded(audio=audio, speech_ms=speech_ms):
                    await self._send(CallerSpeech(active=False))
                    if self._state == "speaking":
                        if speech_ms < self._settings.barge_in_ms:
                            logger.info(
                                "Ignored %d ms of speech over the reply", speech_ms
                            )
                            if self._live is not None:
                                await self._live.clear()
                            continue
                        await self._barge_in()
                    # Committed here, in order with the audio, so the next
                    # utterance can't slip into this one
                    pending = (await self._live.commit(),) if self._live else ()
                    await self._queue(_Spoken(audio, time.perf_counter(), pending))
        if (
            self._state == "speaking"
            and self._endpointer.speech_ms >= self._settings.barge_in_ms
        ):
            await self._barge_in()

    async def _mute(self, muted: bool) -> None:
        self._muted = muted
        if muted and self._endpointer.active:
            self._endpointer.reset()
            if self._live is not None:
                await self._live.clear()
            await self._send(CallerSpeech(active=False))

    async def _queue(self, item: _Input) -> None:
        if isinstance(item, _Spoken):
            for index, waiting in enumerate(self._pending):
                if isinstance(waiting, _Spoken):
                    # The caller went on talking: answer both parts together
                    self._pending[index] = _Spoken(
                        np.concatenate([waiting.audio, _JOIN_SILENCE, item.audio]),
                        item.ended_at,
                        waiting.pending + item.pending,
                    )
                    return
        elif (
            isinstance(item, _Typed) and len(self._pending) >= self._settings.max_queued
        ):
            await self._send(
                CallError(code="busy", message="Please wait for the answer.")
            )
            return
        self._pending.append(item)
        self._input_ready.set()

    async def _barge_in(self) -> None:
        reply = self._reply
        if reply is None or reply.finished:
            return
        logger.info("The caller interrupted turn %d", reply.turn)
        # Decided before anything is awaited, so it happens once
        self._state = "listening"
        if self._turn_scope is not None:
            self._turn_scope.cancel()
        self._playback.drop()
        await self._send(Interrupted(turn=reply.turn))
        await self._send(StateChanged(state="listening"))

    # --- Turns -----------------------------------------------------------------

    async def _take_turns(self) -> None:
        """Answers the caller's input one turn after the other."""
        while True:
            if not self._pending:
                await self._set_state("listening")
                self._input_ready = anyio.Event()
                await self._input_ready.wait()
                continue
            item = self._pending.popleft()
            with anyio.CancelScope() as scope:
                self._turn_scope = scope
                await self._take_turn(item)
            self._turn_scope = None
            self._reply = None

    async def _take_turn(self, item: _Input) -> None:
        self._turn += 1
        turn = self._turn
        if isinstance(item, _Greeting):
            await self._speak_fixed(
                _Reply(turn, "template", time.perf_counter()), GREETING
            )
            return

        await self._set_state("thinking")
        user_timings: dict[str, int] | None = None
        stt: dict[str, float | int | None] | None = None
        source: Source
        if isinstance(item, _Spoken):
            started, source = item.ended_at, "voice"
            recognizing = time.perf_counter()
            try:
                transcript = await self._transcribe(item)
            except Exception:
                logger.exception("Speech recognition failed")
                await self._send(
                    CallError(
                        code="stt_failed",
                        message="Sorry, something went wrong with the speech recognition.",
                    )
                )
                return
            user_timings = {"stt": round((time.perf_counter() - recognizing) * 1000)}
            stt = {
                "audio_ms": transcript.audio_ms,
                "avg_logprob": transcript.avg_logprob,
                "no_speech_prob": transcript.no_speech_prob,
            }
            if heard_nothing(transcript):
                logger.info("Nothing heard: %r %s", transcript.text, stt)
                return
            text = transcript.text
        else:
            started, source, text = item.received_at, item.via, item.text

        conversation_id = self._conversation_id
        assert conversation_id is not None
        # History first, so it doesn't contain the new message twice
        history = await self._repository.recent_messages(
            conversation_id, self._settings.history_messages
        )
        user = await self._repository.add_message(
            conversation_id,
            NewMessage(
                role="user", source=source, text=text, timings_ms=user_timings, stt=stt
            ),
        )
        await self._send(UserMessage(id=user.id, text=user.text, source=user.source))
        reply = _Reply(turn, "llm", started)
        if user_timings:
            reply.timings_ms.update(user_timings)
        await self._answer(reply, history, text)

    async def _transcribe(self, item: _Spoken) -> Transcript:
        """The live transcripts if in use, else (or when they fail) the recording's."""
        if item.pending:
            try:
                parts = [await pending.wait() for pending in item.pending]
            except Exception:
                logger.warning(
                    "Live recognition failed; transcribing the recording",
                    exc_info=True,
                )
            else:
                return Transcript(
                    text=" ".join(part.text for part in parts if part.text),
                    audio_ms=round(len(item.audio) / SAMPLE_RATE * 1000),
                    avg_logprob=None,
                    no_speech_prob=None,
                )
        return await self._recognizer.transcribe(item.audio, trim_silence=False)

    async def _answer(self, reply: _Reply, history: list[Message], text: str) -> None:
        """The model's reply, spoken sentence by sentence as it's written."""
        self._reply = reply
        try:
            sentences, to_speak = anyio.create_memory_object_stream[str](math.inf)
            buffer = SentenceBuffer()

            async def on_text(delta: str) -> None:
                await checkpoint_if_cancelled()
                reply.text += delta
                await self._send(AssistantDelta(turn=reply.turn, text=delta))
                for sentence in buffer.push(delta):
                    sentences.send_nowait(sentence)

            result: StreamedReply | None = None
            async with anyio.create_task_group() as tasks:
                # Speaks sentence k while the model writes sentence k + 1
                tasks.start_soon(self._speak_all, reply, to_speak)
                with sentences:
                    result = await self._responder.stream(history, text, on_text)
                    if not result.failed and (rest := buffer.flush()):
                        sentences.send_nowait(rest)
            assert result is not None

            reply.text, reply.source, reply.usage = (
                result.text,
                result.source,
                result.usage,
            )
            for name, value in (
                ("llm_first_token", result.first_token_ms),
                ("llm_total", result.total_ms),
            ):
                if value is not None:
                    reply.timings_ms[name] = value
            if result.failed:
                reply.failed = True
                # What the model managed to say stays, cut off; then the
                # fixed reply
                with anyio.CancelScope(shield=True):
                    await self._store(reply)
                self._reply = None
                await self._speak_fixed(
                    _Reply(reply.turn, "template", reply.started), LLM_FAILED
                )
                return
            await self._finish(reply)
        finally:
            with anyio.CancelScope(shield=True):
                await self._store(reply)

    async def _speak_fixed(self, reply: _Reply, text: str) -> None:
        """A fixed reply (greeting, fallbacks), spoken sentence by sentence."""
        self._reply = reply
        try:
            reply.text = text
            await self._send(AssistantDelta(turn=reply.turn, text=text))
            buffer = SentenceBuffer()
            for sentence in [*buffer.push(text), buffer.flush()]:
                if sentence:
                    await self._speak(reply, sentence)
            await self._finish(reply)
        finally:
            with anyio.CancelScope(shield=True):
                await self._store(reply)

    async def _speak_all(
        self, reply: _Reply, sentences: anyio.abc.ObjectReceiveStream[str]
    ) -> None:
        async with sentences:
            async for sentence in sentences:
                await self._speak(reply, sentence)

    async def _speak(self, reply: _Reply, sentence: str) -> None:
        """One sentence, sent to the browser piece by piece as it's synthesized."""
        spoken = speakable(sentence)
        if not spoken:
            return
        # Numbered at its first piece, so a sentence without audio has none
        clip: int | None = None
        duration_ms = 0.0

        async def on_audio(chunk: AudioChunk) -> None:
            nonlocal clip, duration_ms
            # Interrupted while the voice was synthesized
            await checkpoint_if_cancelled()
            if clip is None:
                self._clip += 1
                clip = self._clip
                reply.spoken.append((clip, sentence))
                reply.timings_ms.setdefault("first_audio", reply.since_start_ms())
                await self._set_state("speaking")
            duration_ms += chunk.duration_ms
            self._playback.sent(clip, chunk.duration_ms)
            await self._send(
                AudioPiece(
                    clip=clip,
                    turn=reply.turn,
                    sample_rate=chunk.sample_rate,
                    pcm_base64=base64.b64encode(chunk.pcm).decode(),
                )
            )

        try:
            await self._synthesizer.synthesize(spoken, on_audio)
        except Exception:
            # The caller still reads the text, and hears what came so far
            logger.exception("Speech synthesis failed")
        if clip is not None:
            await self._send(
                AudioEnd(
                    clip=clip,
                    turn=reply.turn,
                    text=sentence,
                    duration_ms=round(duration_ms),
                )
            )

    async def _finish(self, reply: _Reply) -> None:
        """Waits until the caller has heard the whole reply."""
        reply.timings_ms["total"] = reply.since_start_ms()
        await self._playback.wait()
        # Talking from now on doesn't interrupt it anymore
        reply.finished = True

    async def _store(self, reply: _Reply) -> None:
        text = reply.text.strip()
        if not text or reply.stored:
            return
        conversation_id = self._conversation_id
        assert conversation_id is not None
        reply.stored = True
        turn = reply.turn
        interrupted = not reply.finished
        heard_text = None
        if interrupted and not reply.failed:
            played = self._playback.played
            heard_text = " ".join(text for clip, text in reply.spoken if clip in played)
        message = await self._repository.add_message(
            conversation_id,
            NewMessage(
                role="assistant",
                source=reply.source,
                text=text,
                timings_ms=reply.timings_ms or None,
                llm_usage=reply.usage,
                interrupted=interrupted,
                heard_text=heard_text,
            ),
        )
        await self._send(
            AssistantMessage(
                id=message.id,
                turn=turn,
                text=message.text,
                source=message.source,
                interrupted=interrupted,
            )
        )
        if not reply.failed:
            await self._send(TurnDone(turn=turn, timings_ms=reply.timings_ms))
        logger.info(
            "Turn %d of %s%s: %s",
            turn,
            conversation_id,
            " (interrupted)" if interrupted else "",
            reply.timings_ms,
        )

    # --- Output ----------------------------------------------------------------

    async def _set_state(self, state: CallState) -> None:
        if self._state != state:
            self._state = state
            await self._send(StateChanged(state=state))

    async def _send(self, message: ServerMessage) -> None:
        await self._transport.send(message)
