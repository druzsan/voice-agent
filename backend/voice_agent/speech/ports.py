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
    # Averages over the recognized segments; None when nothing was recognized.
    # Whisper reports no single confidence score, so none is made up here.
    avg_logprob: float | None
    no_speech_prob: float | None


@dataclass(frozen=True)
class AudioClip:
    wav: bytes
    sample_rate: int
    duration_ms: int


class SpeechRecognizer(Protocol):
    async def transcribe(self, samples: Samples) -> Transcript: ...


class SpeechSynthesizer(Protocol):
    async def synthesize(self, text: str) -> AudioClip: ...
