"""The real speech models: Piper speaks, Whisper hears it back.

Downloads the models into backend/models first if they're missing, like the
app does: `make test-speech`.
"""

import io
import wave

import anyio
import numpy as np
import pytest

from voice_agent.config import Settings
from voice_agent.speech.audio import SAMPLE_RATE
from voice_agent.speech.model_files import ensure_models, piper_voice_file, whisper_dir
from voice_agent.speech.ports import Samples

pytestmark = pytest.mark.speech


def to_16_khz(wav: bytes) -> Samples:
    with wave.open(io.BytesIO(wav), "rb") as reader:
        rate = reader.getframerate()
        pcm = np.frombuffer(reader.readframes(reader.getnframes()), dtype="<i2")
    samples = pcm.astype(np.float32)
    samples /= 32768
    times = np.arange(0, len(samples) / rate, 1 / SAMPLE_RATE)
    resampled = np.interp(times, np.arange(len(samples)) / rate, samples)
    return resampled.astype(np.float32)


def test_piper_speech_is_recognized_by_whisper() -> None:
    from voice_agent.speech.piper import PiperSynthesizer
    from voice_agent.speech.whisper import FasterWhisperRecognizer

    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]
    ensure_models(settings.models_dir, settings.stt_model, settings.tts_voice)
    synthesizer = PiperSynthesizer(
        piper_voice_file(settings.models_dir, settings.tts_voice)
    )
    recognizer = FasterWhisperRecognizer(
        whisper_dir(settings.models_dir, settings.stt_model), beam_size=1
    )

    async def roundtrip() -> str:
        clip = await synthesizer.synthesize("Please call me back tomorrow morning.")
        assert clip.duration_ms > 1000
        transcript = await recognizer.transcribe(to_16_khz(clip.wav))
        assert transcript.no_speech_prob is not None and transcript.no_speech_prob < 0.5
        return transcript.text.lower()

    text = anyio.run(roundtrip)

    assert "call me back" in text
    assert "tomorrow" in text
