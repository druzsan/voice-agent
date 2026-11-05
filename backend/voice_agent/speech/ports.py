from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Protocol

import numpy as np
import numpy.typing as npt

# Mono 16 kHz samples in [-1, 1], the recognizer's input format
Samples = npt.NDArray[np.float32]


@dataclass(frozen=True)
class Transcript:
    text: str
    audio_ms: int
    # Averages over the recognized segments; None when nothing was recognized
    # or the recognizer doesn't report them (OpenAI). Whisper reports no
    # single confidence score, so none is made up here.
    avg_logprob: float | None
    no_speech_prob: float | None


@dataclass(frozen=True)
class AudioClip:
    wav: bytes
    sample_rate: int
    duration_ms: int


@dataclass(frozen=True)
class AudioChunk:
    """A piece of synthesized speech: mono 16-bit little-endian PCM."""

    pcm: bytes
    sample_rate: int

    @property
    def duration_ms(self) -> float:
        return len(self.pcm) / 2 / self.sample_rate * 1000


OnAudio = Callable[[AudioChunk], Awaitable[None]]


class SpeechRecognizer(Protocol):
    async def transcribe(
        self, samples: Samples, *, trim_silence: bool = True
    ) -> Transcript:
        """Recognize English speech.

        trim_silence drops silence around the words first; live calls turn
        it off, because their utterances are already cut at the speech.
        """
        ...


class SpeechSynthesizer(Protocol):
    async def synthesize(self, text: str, on_audio: OnAudio) -> None:
        """Speak English text, passing on the audio as soon as it's generated.

        Every chunk of one call has the same sample rate.
        """
        ...


class PendingTranscript(Protocol):
    async def wait(self) -> Transcript:
        """The transcript; raises when recognition failed or took too long."""
        ...


class LiveTranscription(Protocol):
    """One caller's speech, recognized while they talk."""

    async def append(self, samples: Samples) -> None:
        """More audio of the current utterance. Never raises: lost audio
        fails the utterance's transcript instead."""
        ...

    async def commit(self) -> PendingTranscript:
        """End the current utterance; its transcript follows."""
        ...

    async def clear(self) -> None:
        """Drop the audio of the current utterance."""
        ...


class LiveRecognizer(Protocol):
    def open(self) -> AbstractAsyncContextManager[LiveTranscription]:
        """A session for one call."""
        ...
