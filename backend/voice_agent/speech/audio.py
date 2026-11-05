"""Audio formats: the browser's recordings (WAV with 16 kHz mono 16-bit PCM)
and synthesized speech."""

import io
import wave

import numpy as np

from voice_agent.speech.ports import AudioChunk, AudioClip, Samples, SpeechSynthesizer

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


async def synthesize_clip(synthesizer: SpeechSynthesizer, text: str) -> AudioClip:
    """The whole spoken text as one WAV clip."""
    chunks: list[AudioChunk] = []

    async def collect(chunk: AudioChunk) -> None:
        chunks.append(chunk)

    await synthesizer.synthesize(text, collect)
    if not chunks:
        raise ValueError("The synthesizer produced no audio")
    sample_rate = chunks[0].sample_rate
    pcm = b"".join(chunk.pcm for chunk in chunks)
    return AudioClip(
        wav=write_wav(pcm, sample_rate),
        sample_rate=sample_rate,
        duration_ms=round(len(pcm) / 2 / sample_rate * 1000),
    )


def to_pcm16(samples: Samples) -> bytes:
    """Float samples in [-1, 1] as 16-bit little-endian PCM."""
    return (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()
