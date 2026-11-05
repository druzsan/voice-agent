import io
import wave
from pathlib import Path

import anyio
from anyio import to_thread
from piper import PiperVoice

from voice_agent.speech.ports import AudioChunk, OnAudio


class PiperSynthesizer:
    """Speech synthesis with a local Piper voice, on the CPU."""

    def __init__(self, voice_file: Path) -> None:
        self._voice = PiperVoice.load(voice_file, use_cuda=False)
        # One synthesis at a time; parallel runs would only compete for the cores
        self._limiter = anyio.CapacityLimiter(1)

    async def synthesize(self, text: str, on_audio: OnAudio) -> None:
        # Piper is fast enough to pass on a sentence in one piece
        chunk = await to_thread.run_sync(self._synthesize, text, limiter=self._limiter)
        await on_audio(chunk)

    def _synthesize(self, text: str) -> AudioChunk:
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav:
            self._voice.synthesize_wav(text, wav)
        buffer.seek(0)
        with wave.open(buffer, "rb") as wav:
            return AudioChunk(
                pcm=wav.readframes(wav.getnframes()), sample_rate=wav.getframerate()
            )
