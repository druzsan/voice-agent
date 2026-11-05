"""The recording format the browser sends: WAV with 16 kHz mono 16-bit PCM."""

import io
import wave

import numpy as np

from voice_agent.speech.ports import Samples

SAMPLE_RATE = 16_000
MIN_DURATION_S = 0.2
WAV_HEADER_BYTES = 44


class InvalidAudio(ValueError):
    pass


def max_wav_bytes(max_duration_s: float) -> int:
    return WAV_HEADER_BYTES + int(max_duration_s * SAMPLE_RATE) * 2


def read_wav(data: bytes, max_duration_s: float) -> Samples:
    """Decode a recording into float32 samples, checking its format and length."""
    try:
        with wave.open(io.BytesIO(data), "rb") as wav:
            if wav.getnchannels() != 1 or wav.getsampwidth() != 2:
                raise InvalidAudio("Expected mono 16-bit PCM")
            if wav.getframerate() != SAMPLE_RATE:
                raise InvalidAudio(f"Expected {SAMPLE_RATE} Hz")
            frames = wav.readframes(wav.getnframes())
    except (wave.Error, EOFError) as error:
        raise InvalidAudio("Not a valid WAV file") from error
    samples = np.frombuffer(frames, dtype="<i2").astype(np.float32)
    samples /= 32768
    duration_s = len(samples) / SAMPLE_RATE
    if duration_s < MIN_DURATION_S:
        raise InvalidAudio("Recording is too short")
    if duration_s > max_duration_s:
        raise InvalidAudio(f"Recording is longer than {max_duration_s:g} s")
    return samples


def write_wav(pcm: bytes, sample_rate: int) -> bytes:
    """Wrap mono 16-bit PCM in a WAV container."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return buffer.getvalue()
