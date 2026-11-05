"""The real speech models: Piper speaks, the voice detection finds it, Whisper hears it.

Downloads the models into backend/models first if they're missing, like the
app does: `make test-speech`.
"""

import io
import wave
from typing import TYPE_CHECKING

import anyio
import numpy as np
import pytest

from voice_agent.config import Settings
from voice_agent.speech.audio import SAMPLE_RATE, synthesize_clip
from voice_agent.speech.model_files import ensure_models, piper_voice_file, whisper_dir
from voice_agent.speech.ports import Samples
from voice_agent.speech.vad import (
    Endpointer,
    EndpointerSettings,
    SileroVad,
    SpeechAudio,
    SpeechEnded,
    SpeechStarted,
)

if TYPE_CHECKING:
    from voice_agent.speech.piper import PiperSynthesizer
    from voice_agent.speech.whisper import FasterWhisperRecognizer

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


@pytest.fixture(scope="module")
def models() -> tuple["PiperSynthesizer", "FasterWhisperRecognizer"]:
    from voice_agent.speech.piper import PiperSynthesizer
    from voice_agent.speech.whisper import FasterWhisperRecognizer

    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]
    ensure_models(settings.models_dir, settings.stt_model, settings.tts_voice)
    return (
        PiperSynthesizer(piper_voice_file(settings.models_dir, settings.tts_voice)),
        FasterWhisperRecognizer(
            whisper_dir(settings.models_dir, settings.stt_model), beam_size=1
        ),
    )


def test_piper_speech_is_recognized_by_whisper(
    models: tuple["PiperSynthesizer", "FasterWhisperRecognizer"],
) -> None:
    synthesizer, recognizer = models

    async def roundtrip() -> str:
        clip = await synthesize_clip(
            synthesizer, "Please call me back tomorrow morning."
        )
        assert clip.duration_ms > 1000
        transcript = await recognizer.transcribe(to_16_khz(clip.wav))
        assert transcript.no_speech_prob is not None and transcript.no_speech_prob < 0.5
        return transcript.text.lower()

    text = anyio.run(roundtrip)

    assert "call me back" in text
    assert "tomorrow" in text


def test_the_voice_detection_cuts_speech_out_of_silence(
    models: tuple["PiperSynthesizer", "FasterWhisperRecognizer"],
) -> None:
    synthesizer, recognizer = models
    clip = anyio.run(synthesize_clip, synthesizer, "I'd like to book a table for two.")
    speech = to_16_khz(clip.wav)
    silence = np.zeros(SAMPLE_RATE, dtype=np.float32)
    audio = np.concatenate([silence, speech, silence, silence])
    endpointer = Endpointer(SileroVad().stream(), EndpointerSettings())

    # In 32 ms frames, as the browser sends them
    pcm = (audio * 32767).astype("<i2").tobytes()
    events = [
        event
        for start in range(0, len(pcm), 1024)
        for event in endpointer.feed(pcm[start : start + 1024])
        if not isinstance(event, SpeechAudio)
    ]

    assert [type(event) for event in events] == [SpeechStarted, SpeechEnded]
    utterance = events[1]
    assert isinstance(utterance, SpeechEnded)
    speech_s = len(speech) / SAMPLE_RATE
    assert 0.6 * speech_s < utterance.speech_ms / 1000 <= speech_s
    # Most of the padding is cut away
    assert len(utterance.audio) / SAMPLE_RATE < speech_s + 1
    transcript = anyio.run(
        lambda: recognizer.transcribe(utterance.audio, trim_silence=False)
    )
    assert "table for two" in transcript.text.lower()
