"""Speech recognition and synthesis with OpenAI's speech models.

The same models run on Azure OpenAI's v1 API; only the base URL, the key
and the model (deployment) names differ.
"""

import base64
import json
from typing import Any

from openai import AsyncOpenAI

from voice_agent.speech.audio import SAMPLE_RATE, to_pcm16, write_wav
from voice_agent.speech.ports import AudioChunk, OnAudio, Samples, Transcript
from voice_agent.usage import PRICE_PER_MINUTE, Usage, listed_cost

# The speech endpoint's raw PCM: 24 kHz mono 16-bit little-endian
TTS_SAMPLE_RATE = 24_000
# Audio is passed on in pieces of at least 100 ms: small enough to start
# playing early, large enough not to flood the connection with messages
TTS_CHUNK_BYTES = TTS_SAMPLE_RATE * 2 // 10


def openai_client(
    api_key: str, base_url: str, timeout_s: float, max_retries: int = 1
) -> AsyncOpenAI:
    # One retry at most: a caller on the phone can't wait much longer
    return AsyncOpenAI(
        api_key=api_key, base_url=base_url, timeout=timeout_s, max_retries=max_retries
    )


def transcription_usage(model: str, usage: Any, audio_s: float) -> Usage:
    """A transcription's usage, billed by tokens or by audio duration.

    `usage` is any of the SDK's transcription usage objects (they share the
    fields), or None when the API reported none.
    """
    name = f"openai/{model}"
    if usage is None:
        return Usage(
            service="stt", model=name, audio_in_s=round(audio_s, 3), cost_usd=None
        )
    if usage.type == "duration":
        price = PRICE_PER_MINUTE.get(model)
        return Usage(
            service="stt",
            model=name,
            audio_in_s=round(usage.seconds, 3),
            cost_usd=None if price is None else usage.seconds * price / 60,
        )
    details = usage.input_token_details
    return Usage(
        service="stt",
        model=name,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        audio_in_s=round(audio_s, 3),
        cost_usd=listed_cost(
            model,
            "openai",
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            input_audio_tokens=(details and details.audio_tokens) or 0,
        ),
    )


class OpenAIRecognizer:
    """English speech recognition of whole recordings with an OpenAI model."""

    def __init__(self, client: AsyncOpenAI, model: str) -> None:
        self._client = client
        self._model = model

    async def transcribe(
        self, samples: Samples, *, trim_silence: bool = True
    ) -> Transcript:
        # The model needs no trimming: it doesn't invent words for silence
        # the way Whisper does
        wav = write_wav(to_pcm16(samples), SAMPLE_RATE)
        result = await self._client.audio.transcriptions.create(
            model=self._model, file=("speech.wav", wav), language="en"
        )
        audio_s = len(samples) / SAMPLE_RATE
        return Transcript(
            text=result.text.strip(),
            audio_ms=round(audio_s * 1000),
            avg_logprob=None,
            no_speech_prob=None,
            usage=transcription_usage(self._model, result.usage, audio_s),
        )


class OpenAISynthesizer:
    """English speech synthesis with an OpenAI model, streamed as it's generated.

    The stream comes as server-sent events, the only form that reports the
    tokens used.
    """

    def __init__(
        self,
        client: AsyncOpenAI,
        model: str,
        voice: str,
        instructions: str,
        speed: float = 1.0,
    ) -> None:
        self._client = client
        self._model = model
        self._voice = voice
        self._instructions = instructions
        self._speed = speed

    async def synthesize(self, text: str, on_audio: OnAudio) -> Usage:
        pending = b""
        samples = 0
        usage: dict[str, int] | None = None

        async def flush(*, final: bool) -> None:
            nonlocal pending, samples
            # A piece can end within a sample; its byte waits for the next
            whole = len(pending) - len(pending) % 2
            if whole and (final or whole >= TTS_CHUNK_BYTES):
                pcm, pending = pending[:whole], pending[whole:]
                samples += len(pcm) // 2
                await on_audio(AudioChunk(pcm, TTS_SAMPLE_RATE))

        async with self._client.audio.speech.with_streaming_response.create(
            model=self._model,
            voice=self._voice,
            input=text,
            instructions=self._instructions,
            speed=self._speed,
            response_format="pcm",
            stream_format="sse",
        ) as response:
            async for line in response.iter_lines():
                data = line.removeprefix("data:").strip()
                # The stream ends with [DONE] after the last event
                if not line.startswith("data:") or data == "[DONE]":
                    continue
                event = json.loads(data)
                if event["type"] == "speech.audio.delta":
                    pending += base64.b64decode(event["audio"])
                    await flush(final=False)
                elif event["type"] == "speech.audio.done":
                    usage = event.get("usage")
        await flush(final=True)
        return self._usage(usage, samples / TTS_SAMPLE_RATE)

    def _usage(self, usage: dict[str, int] | None, audio_s: float) -> Usage:
        name = f"openai/{self._model}/{self._voice}"
        if usage is None:
            return Usage(
                service="tts", model=name, audio_out_s=round(audio_s, 3), cost_usd=None
            )
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)
        return Usage(
            service="tts",
            model=name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            audio_out_s=round(audio_s, 3),
            # The model speaks only audio
            cost_usd=listed_cost(
                self._model,
                "openai",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                output_audio_tokens=output_tokens,
            ),
        )
