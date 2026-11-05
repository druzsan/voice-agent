"""OpenAI's speech models: OpenAI speaks, file and live transcription hear it.

Needs OPENAI_API_KEY (read like the app reads it) and costs a few cents:
`make test-openai`.
"""

from collections.abc import AsyncGenerator

import numpy as np
import pytest
from openai import AsyncOpenAI

from tests.speech.test_roundtrip import to_16_khz
from voice_agent.config import Settings
from voice_agent.speech.audio import SAMPLE_RATE, synthesize_clip
from voice_agent.speech.openai_live import OpenAILiveRecognizer
from voice_agent.speech.openai_speech import (
    OpenAIRecognizer,
    OpenAISynthesizer,
    openai_client,
)
from voice_agent.speech.ports import Samples
from voice_agent.speech.vad import (
    Endpointer,
    EndpointerSettings,
    SileroVad,
    SpeechAudio,
    SpeechEnded,
)

pytestmark = [pytest.mark.openai, pytest.mark.anyio]

SENTENCE = "Please call me back tomorrow morning about my delivery."


@pytest.fixture
def settings() -> Settings:
    settings = Settings()
    if settings.openai_api_key is None:
        pytest.skip("OPENAI_API_KEY is not set")
    return settings


@pytest.fixture
async def client(settings: Settings) -> AsyncGenerator[AsyncOpenAI]:
    assert settings.openai_api_key is not None
    client = openai_client(
        settings.openai_api_key.get_secret_value(),
        settings.openai_base_url,
        settings.openai_timeout_s,
    )
    yield client
    await client.close()


@pytest.fixture
async def speech(settings: Settings, client: AsyncOpenAI) -> Samples:
    synthesizer = OpenAISynthesizer(
        client,
        settings.openai_tts_model,
        settings.openai_tts_voice,
        settings.openai_tts_instructions,
        settings.openai_tts_speed,
    )
    clip = await synthesize_clip(synthesizer, SENTENCE)
    assert clip.sample_rate == 24_000
    assert clip.duration_ms > 1500
    return to_16_khz(clip.wav)


def heard(text: str) -> bool:
    text = text.lower()
    return "call me back" in text and "tomorrow" in text


async def test_file_transcription_hears_openai_speech(
    settings: Settings, client: AsyncOpenAI, speech: Samples
) -> None:
    recognizer = OpenAIRecognizer(client, settings.openai_stt_model)

    transcript = await recognizer.transcribe(speech)

    assert heard(transcript.text), transcript.text


async def test_live_transcription_hears_speech_as_the_call_streams_it(
    settings: Settings, client: AsyncOpenAI, speech: Samples
) -> None:
    silence = np.zeros(SAMPLE_RATE, dtype=np.float32)
    audio = np.concatenate([silence, speech, silence])
    pcm = (audio * 32767).astype("<i2").tobytes()
    endpointer = Endpointer(SileroVad().stream(), EndpointerSettings())
    recognizer = OpenAILiveRecognizer(
        client, settings.openai_live_stt_model, settings.openai_timeout_s
    )

    async with recognizer.open() as live:
        pending = None
        # In 32 ms frames, as the browser sends them
        for start in range(0, len(pcm), 1024):
            for event in endpointer.feed(pcm[start : start + 1024]):
                if isinstance(event, SpeechAudio):
                    await live.append(event.audio)
                elif isinstance(event, SpeechEnded):
                    pending = await live.commit()
        assert pending is not None, "no utterance found"
        transcript = await pending.wait()

    assert heard(transcript.text), transcript.text
