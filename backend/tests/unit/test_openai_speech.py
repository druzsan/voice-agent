"""The OpenAI speech adapters against a scripted API: no network, no key."""

import base64
import io
import json
import wave
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any, cast

import anyio
import anyio.lowlevel
import httpx2
import numpy as np
import pytest
from openai import AsyncOpenAI

from voice_agent.speech.audio import synthesize_clip
from voice_agent.speech.openai_live import (
    OpenAILiveRecognizer,
    Upsampler,
)
from voice_agent.speech.openai_speech import (
    OpenAIRecognizer,
    OpenAISynthesizer,
    transcription_usage,
)
from voice_agent.speech.ports import AudioChunk

pytestmark = pytest.mark.anyio


def client(handle: Any) -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key="key",
        base_url="https://api.example.com/v1",
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handle)),
    )


def sse(*events: dict[str, Any]) -> bytes:
    data = [json.dumps(event) for event in events] + ["[DONE]"]
    return "".join(f"data: {item}\n\n" for item in data).encode()


def audio_delta(pcm: bytes) -> dict[str, Any]:
    return {"type": "speech.audio.delta", "audio": base64.b64encode(pcm).decode()}


async def test_a_recording_is_sent_as_english_wav() -> None:
    requests: list[httpx2.Request] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(
            200,
            json={
                "text": " My car is late. ",
                "usage": {
                    "type": "tokens",
                    "input_tokens": 1000,
                    "output_tokens": 100,
                    "total_tokens": 1100,
                    "input_token_details": {"audio_tokens": 1000, "text_tokens": 0},
                },
            },
        )

    recognizer = OpenAIRecognizer(client(handle), "gpt-4o-mini-transcribe")
    samples = np.zeros(24_000, dtype=np.float32)

    transcript = await recognizer.transcribe(samples)

    body = requests[0].content
    assert requests[0].url.path == "/v1/audio/transcriptions"
    assert b'filename="speech.wav"' in body and b"RIFF" in body
    assert b'name="language"\r\n\r\nen' in body
    assert b'name="model"\r\n\r\ngpt-4o-mini-transcribe' in body
    assert transcript.text == "My car is late."
    assert transcript.audio_ms == 1500
    assert (transcript.avg_logprob, transcript.no_speech_prob) == (None, None)
    usage = transcript.usage
    assert usage is not None
    assert (usage.service, usage.model) == ("stt", "openai/gpt-4o-mini-transcribe")
    assert (usage.input_tokens, usage.output_tokens, usage.audio_in_s) == (
        1000,
        100,
        1.5,
    )
    # $3 per million audio tokens in, $5 per million text tokens out
    assert usage.cost_usd == pytest.approx(0.003 + 0.0005)


def test_live_transcription_by_duration_is_priced_per_minute() -> None:
    usage = transcription_usage(
        "gpt-live-transcribe", SimpleNamespace(type="duration", seconds=30.0), 29.5
    )

    assert usage.audio_in_s == 30.0
    assert usage.cost_usd == pytest.approx(0.017 / 2)


def test_a_transcription_without_usage_has_an_unknown_cost() -> None:
    usage = transcription_usage("gpt-live-transcribe", None, 2.0)

    assert (usage.audio_in_s, usage.cost_usd) == (2.0, None)


async def test_speech_is_passed_on_in_whole_samples_as_it_arrives() -> None:
    requests: list[httpx2.Request] = []
    # Half a second of 24 kHz audio, in events that split a sample
    pcm = np.arange(12_000, dtype="<i2").tobytes()

    def handle(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=sse(
                audio_delta(pcm[:3_001]),
                audio_delta(pcm[3_001:9_999]),
                audio_delta(pcm[9_999:]),
                {
                    "type": "speech.audio.done",
                    "usage": {
                        "input_tokens": 100,
                        "output_tokens": 1000,
                        "total_tokens": 1100,
                    },
                },
            ),
        )

    synthesizer = OpenAISynthesizer(
        client(handle), "gpt-4o-mini-tts", "marin", "Brisk.", 1.25
    )
    chunks: list[AudioChunk] = []

    async def collect(chunk: AudioChunk) -> None:
        chunks.append(chunk)

    usage = await synthesizer.synthesize("Hello there.", collect)

    sent = json.loads(requests[0].content)
    assert sent == {
        "model": "gpt-4o-mini-tts",
        "voice": "marin",
        "input": "Hello there.",
        "instructions": "Brisk.",
        "speed": 1.25,
        "response_format": "pcm",
        "stream_format": "sse",
    }
    # Pieces of at least 100 ms (but the last), every one in whole samples
    assert {chunk.sample_rate for chunk in chunks} == {24_000}
    assert all(len(chunk.pcm) % 2 == 0 for chunk in chunks)
    assert all(len(chunk.pcm) >= 4_800 for chunk in chunks[:-1])
    assert b"".join(chunk.pcm for chunk in chunks) == pcm
    assert (usage.service, usage.model) == ("tts", "openai/gpt-4o-mini-tts/marin")
    assert (usage.input_tokens, usage.output_tokens) == (100, 1000)
    assert usage.audio_out_s == 0.5
    # $0.60 per million text tokens in, $12 per million audio tokens out
    assert usage.cost_usd == pytest.approx(0.00006 + 0.012)


async def test_speech_collected_into_a_wav() -> None:
    def handle(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=sse(audio_delta(bytes(48_000)), {"type": "speech.audio.done"}),
        )

    synthesizer = OpenAISynthesizer(client(handle), "gpt-4o-mini-tts", "marin", "")

    clip = await synthesize_clip(synthesizer, "Hello.")

    assert (clip.sample_rate, clip.duration_ms) == (24_000, 1000)
    with wave.open(io.BytesIO(clip.wav), "rb") as wav:
        assert wav.getframerate() == 24_000 and wav.getnframes() == 24_000
    # Without usage in the stream, the cost isn't known
    assert clip.usage is not None and clip.usage.cost_usd is None


def test_live_audio_is_raised_to_24_khz_across_chunks() -> None:
    upsampler = Upsampler()
    # A rising 16 kHz ramp, in chunks of odd sizes
    ramp = np.linspace(-0.5, 0.5, 16_000, dtype=np.float32)
    pieces = [ramp[i : i + 333] for i in range(0, 16_000, 333)]

    output = np.frombuffer(
        b"".join(upsampler.feed(piece) for piece in pieces), dtype="<i2"
    )

    # One second stays one second, give or take the last sample
    assert abs(len(output) - 24_000) <= 2
    # The ramp continues smoothly over the chunk boundaries
    steps = np.diff(output.astype(np.int32))
    assert np.all(steps >= 0) and np.max(steps) <= 2


# --- Live transcription against a scripted Realtime connection -----------------


class FakeConnection:
    """Answers each commit with the committed item and, later, its transcript."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, Any]] = []
        self.transcripts: list[str] = []
        self.fail_transcription = False
        self._events_in, self._events = anyio.create_memory_object_stream[Any](100)
        self._items = 0
        self.session = SimpleNamespace(update=self._update)
        self.input_audio_buffer = SimpleNamespace(
            append=self._append, commit=self._commit, clear=self._clear
        )

    async def _update(self, session: dict[str, Any]) -> None:
        self.sent.append(("session.update", session))

    async def _append(self, audio: str) -> None:
        self.sent.append(("append", len(base64.b64decode(audio))))

    async def _clear(self) -> None:
        self.sent.append(("clear", None))

    async def _commit(self) -> None:
        self.sent.append(("commit", None))
        self._items += 1
        item = f"item_{self._items}"
        await self._events_in.send(
            SimpleNamespace(type="input_audio_buffer.committed", item_id=item)
        )
        if self.fail_transcription:
            await self._events_in.send(
                SimpleNamespace(
                    type="conversation.item.input_audio_transcription.failed",
                    item_id=item,
                    error=SimpleNamespace(message="no speech"),
                )
            )
        else:
            await self._events_in.send(
                SimpleNamespace(
                    type="conversation.item.input_audio_transcription.completed",
                    item_id=item,
                    transcript=self.transcripts.pop(0),
                )
            )

    def drop(self) -> None:
        """The connection is lost."""
        self._events_in.close()

    def __aiter__(self) -> AsyncIterator[Any]:
        return self._events.__aiter__()


class FakeRealtime:
    def __init__(self) -> None:
        self.connections: list[FakeConnection] = []
        self.queries: list[dict[str, str]] = []

    @asynccontextmanager
    async def connect(
        self, *, extra_query: dict[str, str]
    ) -> AsyncGenerator[FakeConnection]:
        self.queries.append(extra_query)
        connection = FakeConnection()
        self.connections.append(connection)
        yield connection


def live_client(realtime: FakeRealtime) -> AsyncOpenAI:
    return cast(AsyncOpenAI, SimpleNamespace(realtime=realtime))


async def settled() -> None:
    """Lets the sender task carry out what's queued."""
    for _ in range(20):
        await anyio.lowlevel.checkpoint()


async def test_live_speech_is_transcribed_per_committed_utterance() -> None:
    realtime = FakeRealtime()
    recognizer = OpenAILiveRecognizer(live_client(realtime), "gpt-live-transcribe", 1)

    async with recognizer.open() as live:
        await settled()
        connection = realtime.connections[0]
        connection.transcripts = ["Hello.", "My car is late."]
        await live.append(np.zeros(1_600, dtype=np.float32))
        await live.append(np.zeros(1_600, dtype=np.float32))
        first = await live.commit()
        await live.append(np.zeros(3_200, dtype=np.float32))
        second = await live.commit()

        assert (await first.wait()).text == "Hello."
        transcript = await second.wait()

    assert transcript.text == "My car is late."
    assert transcript.audio_ms == 200
    assert realtime.queries == [{"intent": "transcription"}]
    kind, session = connection.sent[0]
    assert kind == "session.update"
    audio_input = session["audio"]["input"]
    assert audio_input["format"] == {"type": "audio/pcm", "rate": 24_000}
    assert audio_input["transcription"] == {
        "model": "gpt-live-transcribe",
        "language": "en",
    }
    assert audio_input["turn_detection"] is None
    # 0.2 s at 24 kHz, as PCM16, give or take the sample held for the next chunk
    appended = [size for kind, size in connection.sent if kind == "append"]
    assert abs(sum(appended[:2]) - 0.2 * 24_000 * 2) <= 4
    assert [kind for kind, _ in connection.sent[1:]] == [
        "append",
        "append",
        "commit",
        "append",
        "commit",
    ]


async def test_a_failed_live_transcription_fails_its_utterance_only() -> None:
    realtime = FakeRealtime()
    recognizer = OpenAILiveRecognizer(live_client(realtime), "gpt-live-transcribe", 1)

    async with recognizer.open() as live:
        await settled()
        connection = realtime.connections[0]
        connection.fail_transcription = True
        await live.append(np.zeros(1_600, dtype=np.float32))
        pending = await live.commit()

        with pytest.raises(RuntimeError, match="no speech"):
            await pending.wait()


async def test_audio_lost_with_the_connection_fails_the_utterance() -> None:
    realtime = FakeRealtime()
    recognizer = OpenAILiveRecognizer(live_client(realtime), "gpt-live-transcribe", 1)

    async with recognizer.open() as live:
        await settled()
        await live.append(np.zeros(1_600, dtype=np.float32))
        await settled()
        realtime.connections[0].drop()
        await settled()
        await live.append(np.zeros(1_600, dtype=np.float32))
        lost = await live.commit()

        with pytest.raises(ConnectionError):
            await lost.wait()

        # The next utterance connects again
        await live.append(np.zeros(1_600, dtype=np.float32))
        await settled()
        assert len(realtime.connections) == 2
        realtime.connections[1].transcripts = ["Still there?"]
        assert (await (await live.commit()).wait()).text == "Still there?"


async def test_a_cleared_utterance_is_never_committed() -> None:
    realtime = FakeRealtime()
    recognizer = OpenAILiveRecognizer(live_client(realtime), "gpt-live-transcribe", 1)

    async with recognizer.open() as live:
        await live.append(np.zeros(1_600, dtype=np.float32))
        await live.clear()
        await settled()

    kinds = [kind for kind, _ in realtime.connections[0].sent]
    assert kinds == ["session.update", "append", "clear"]
