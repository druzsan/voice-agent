"""Live speech recognition over OpenAI's Realtime API.

The caller's audio goes to the model while they speak, so the transcript is
ready shortly after they stop. Our own voice detection decides where an
utterance ends and commits it; the API's turn detection is off. One session
serves one call: it connects when the call starts and again on the next use
after the connection was lost.

Nothing here makes the call wait for the network: audio and commits are
queued and sent by a background task. A lost connection or lost audio fails
the utterance's transcript, so the caller's recording is transcribed as a
file instead.
"""

import base64
import logging
import math
from collections import deque
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import anyio
import numpy as np
from anyio.abc import TaskGroup, TaskStatus
from openai import AsyncOpenAI
from openai.resources.realtime.realtime import AsyncRealtimeConnection

from voice_agent.speech.audio import SAMPLE_RATE
from voice_agent.speech.openai_speech import transcription_usage
from voice_agent.speech.ports import Samples, Transcript

logger = logging.getLogger(__name__)

# The Realtime API takes 24 kHz mono PCM16; the microphone streams 16 kHz
REALTIME_RATE = 24_000
# After a failed connection attempt, audio is dropped (and its utterance
# transcribed as a file) for this long before the next attempt
RECONNECT_AFTER_S = 5.0


class Upsampler:
    """16 to 24 kHz by linear interpolation, continuous across chunks."""

    _STEP = SAMPLE_RATE / REALTIME_RATE

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._tail = np.zeros(0, dtype=np.float32)
        self._position = 0.0

    def feed(self, samples: Samples) -> bytes:
        """The samples at 24 kHz as PCM16; the last one waits for the next chunk."""
        joined = np.concatenate([self._tail, samples])
        positions = np.arange(self._position, len(joined) - 1, self._STEP)
        output = np.interp(positions, np.arange(len(joined)), joined)
        following = positions[-1] + self._STEP if len(positions) else self._position
        kept = int(following)
        self._tail = joined[kept:]
        self._position = following - kept
        return (np.clip(output, -1, 1) * 32767).astype("<i2").tobytes()


class _Pending:
    """The transcript of a committed utterance, once the model has it."""

    def __init__(self, audio_ms: int, timeout_s: float) -> None:
        self.audio_ms = audio_ms
        self._timeout_s = timeout_s
        self._done = anyio.Event()
        self._transcript: Transcript | None = None
        self._error: Exception | None = None

    def resolve(self, text: str, model: str, usage: Any) -> None:
        if not self._done.is_set():
            self._transcript = Transcript(
                text=text.strip(),
                audio_ms=self.audio_ms,
                avg_logprob=None,
                no_speech_prob=None,
                usage=transcription_usage(model, usage, self.audio_ms / 1000),
            )
            self._done.set()

    def fail(self, error: Exception) -> None:
        if not self._done.is_set():
            self._error = error
            self._done.set()

    async def wait(self) -> Transcript:
        with anyio.fail_after(self._timeout_s):
            await self._done.wait()
        if self._error is not None:
            raise self._error
        assert self._transcript is not None
        return self._transcript


# What the sender task does, in the order the call asked for it
@dataclass(frozen=True)
class _Append:
    pcm: bytes


@dataclass(frozen=True)
class _Commit:
    pending: _Pending


@dataclass(frozen=True)
class _Clear:
    pass


_Command = _Append | _Commit | _Clear


class OpenAILiveTranscription:
    """One call's speech in a Realtime transcription session."""

    def __init__(
        self, client: AsyncOpenAI, model: str, group: TaskGroup, timeout_s: float
    ) -> None:
        self._client = client
        self._model = model
        self._group = group
        self._timeout_s = timeout_s
        self._upsampler = Upsampler()
        # Input samples of the current utterance
        self._samples = 0
        self._commands_in, self._commands = anyio.create_memory_object_stream[_Command](
            math.inf
        )
        self._connection: AsyncRealtimeConnection | None = None
        self._retry_at = 0.0
        # Audio of the current utterance went to the model
        self._appended = False
        # Audio of the current utterance didn't reach the model (completely)
        self._lost = False
        # Commits in the order sent, until the server names their item
        self._committing: deque[_Pending] = deque()
        self._items: dict[str, _Pending] = {}

    # --- The call's side: never waits for the network --------------------------

    async def append(self, samples: Samples) -> None:
        self._samples += len(samples)
        self._commands_in.send_nowait(_Append(self._upsampler.feed(samples)))

    async def commit(self) -> _Pending:
        pending = _Pending(round(self._samples / SAMPLE_RATE * 1000), self._timeout_s)
        self._reset()
        self._commands_in.send_nowait(_Commit(pending))
        return pending

    async def clear(self) -> None:
        self._reset()
        self._commands_in.send_nowait(_Clear())

    def _reset(self) -> None:
        self._upsampler.reset()
        self._samples = 0

    # --- The sender task ---------------------------------------------------------

    async def send_all(self) -> None:
        """Connects right away, then carries out the queued commands in order."""
        try:
            await self._connected()
        except Exception:
            logger.exception("Live transcription couldn't connect")
        async with self._commands:
            async for command in self._commands:
                await self._carry_out(command)

    async def _carry_out(self, command: _Command) -> None:
        match command:
            case _Append(pcm=pcm):
                if self._lost or not pcm:
                    return
                try:
                    connection = await self._connected()
                    await connection.input_audio_buffer.append(
                        audio=base64.b64encode(pcm).decode()
                    )
                    self._appended = True
                except Exception:
                    logger.warning("Live transcription lost audio", exc_info=True)
                    self._lost = True
            case _Commit(pending=pending):
                lost, self._lost, self._appended = self._lost, False, False
                if lost:
                    pending.fail(ConnectionError("Audio of the utterance was lost"))
                    await self._clear_buffer()
                    return
                try:
                    connection = await self._connected()
                    self._committing.append(pending)
                    await connection.input_audio_buffer.commit()
                except Exception as error:
                    logger.warning("Couldn't commit live audio", exc_info=True)
                    if pending in self._committing:
                        self._committing.remove(pending)
                    pending.fail(error)
            case _Clear():
                self._lost = self._appended = False
                await self._clear_buffer()

    async def _clear_buffer(self) -> None:
        if self._connection is not None:
            try:
                await self._connection.input_audio_buffer.clear()
            except Exception:
                logger.warning("Couldn't clear live audio", exc_info=True)

    async def _connected(self) -> AsyncRealtimeConnection:
        if self._connection is not None:
            return self._connection
        if anyio.current_time() < self._retry_at:
            raise ConnectionError("Live transcription is reconnecting")
        try:
            with anyio.fail_after(self._timeout_s):
                connection = await self._group.start(self._run)
        except BaseException:
            self._retry_at = anyio.current_time() + RECONNECT_AFTER_S
            raise
        self._connection = connection
        return connection

    async def _run(self, *, task_status: TaskStatus[AsyncRealtimeConnection]) -> None:
        started = False
        try:
            # The SDK's own reconnect stays off: it would lose the settings
            async with self._client.realtime.connect(
                extra_query={"intent": "transcription"}
            ) as connection:
                await connection.session.update(
                    session={
                        "type": "transcription",
                        "audio": {
                            "input": {
                                "format": {"type": "audio/pcm", "rate": REALTIME_RATE},
                                "transcription": {
                                    "model": self._model,
                                    "language": "en",
                                },
                                # Our own voice detection ends utterances
                                "turn_detection": None,
                            }
                        },
                    }
                )
                task_status.started(connection)
                started = True
                logger.info("Live transcription connected (%s)", self._model)
                async for event in connection:
                    self._handle(event)
        except Exception as error:
            if not started:
                raise
            logger.exception("Live transcription session failed")
            self._fail_waiting(error)
        finally:
            if started:
                self._connection = None
                # What the current utterance sent is gone with the session
                self._lost = self._lost or self._appended
                self._fail_waiting(ConnectionError("Live transcription closed"))

    def _handle(self, event: Any) -> None:
        match event.type:
            case "input_audio_buffer.committed":
                if self._committing:
                    self._items[event.item_id] = self._committing.popleft()
            case "conversation.item.input_audio_transcription.completed":
                if pending := self._items.pop(event.item_id, None):
                    pending.resolve(
                        event.transcript, self._model, getattr(event, "usage", None)
                    )
            case "conversation.item.input_audio_transcription.failed":
                if pending := self._items.pop(event.item_id, None):
                    pending.fail(RuntimeError(event.error.message))
            case "error":
                logger.error("Live transcription error: %s", event.error)
                # An error answers the oldest command, e.g. an empty commit
                if self._committing:
                    self._committing.popleft().fail(RuntimeError(event.error.message))
            case _:
                pass

    def _fail_waiting(self, error: Exception) -> None:
        for pending in [*self._committing, *self._items.values()]:
            pending.fail(error)
        self._committing.clear()
        self._items.clear()


class OpenAILiveRecognizer:
    """Opens a live transcription session per call."""

    def __init__(self, client: AsyncOpenAI, model: str, timeout_s: float) -> None:
        self._client = client
        self._model = model
        self._timeout_s = timeout_s

    @asynccontextmanager
    async def open(self) -> AsyncGenerator[OpenAILiveTranscription]:
        async with anyio.create_task_group() as group:
            session = OpenAILiveTranscription(
                self._client, self._model, group, self._timeout_s
            )
            group.start_soon(session.send_all)
            try:
                yield session
            finally:
                group.cancel_scope.cancel()
