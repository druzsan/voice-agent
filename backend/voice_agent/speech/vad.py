"""Hands-free turns: where the caller's speech starts and ends.

`SileroVad` scores each 32 ms frame of the microphone stream with the speech
probability of the Silero VAD model that faster-whisper ships (ONNX, no
PyTorch). `Endpointer` turns these scores into utterances.
"""

# onnxruntime and faster-whisper ship without type information
# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import numpy as np

from voice_agent.speech.audio import SAMPLE_RATE
from voice_agent.speech.ports import Samples

# Silero VAD scores frames of 512 samples (32 ms) at 16 kHz
FRAME_SAMPLES = 512
FRAME_MS = FRAME_SAMPLES * 1000 // SAMPLE_RATE

# Scores one frame; keeps the state of one microphone stream between calls
SpeechProbability = Callable[[Samples], float]


class VoiceActivityDetector(Protocol):
    def stream(self) -> SpeechProbability:
        """A scorer for one new microphone stream."""
        ...


class SileroVad:
    """The Silero VAD model, shared by all calls; each call gets its own state."""

    CONTEXT_SAMPLES = 64

    def __init__(self, model_file: Path | None = None) -> None:
        import onnxruntime

        if model_file is None:
            import faster_whisper

            model_file = (
                Path(faster_whisper.__file__).parent / "assets" / "silero_vad_v6.onnx"
            )
        options = onnxruntime.SessionOptions()
        # One frame at a time is far too little work to share between threads
        options.inter_op_num_threads = 1
        options.intra_op_num_threads = 1
        options.log_severity_level = 4
        self._session = onnxruntime.InferenceSession(
            str(model_file), providers=["CPUExecutionProvider"], sess_options=options
        )

    def stream(self) -> SpeechProbability:
        state = np.zeros((2, 1, 1, 128), dtype=np.float32)
        context = np.zeros(self.CONTEXT_SAMPLES, dtype=np.float32)

        def probability(frame: Samples) -> float:
            nonlocal context
            # The model sees each frame with the end of the previous one
            window = np.concatenate([context, frame])[np.newaxis, :]
            outputs = self._session.run(
                None, {"input": window, "h": state[0], "c": state[1]}
            )
            speech, h, c = (np.asarray(output) for output in outputs)
            state[0], state[1] = h, c
            context = frame[-self.CONTEXT_SAMPLES :]
            return float(speech.reshape(-1)[0])

        return probability


@dataclass(frozen=True)
class EndpointerSettings:
    # Speech probability that counts as speech, and the lower one that counts
    # as silence again (hysteresis, so a wavering score doesn't flip-flop)
    threshold: float = 0.5
    silence_threshold: float = 0.35
    # This much speech in a row starts an utterance
    start_ms: int = 160
    # This much silence ends it
    silence_ms: int = 700
    # Audio from before the start that belongs to the utterance (the start of
    # the first word scores low)
    pre_roll_ms: int = 320
    # Silence kept at the end of an utterance
    tail_ms: int = 160
    # An utterance ends here even without a pause
    max_utterance_ms: int = 30_000


@dataclass(frozen=True)
class SpeechStarted:
    pass


@dataclass(frozen=True)
class SpeechAudio:
    """The current utterance's audio since the last SpeechAudio.

    Together they make up the utterance (pre-roll included), so it can be
    recognized while the caller still speaks. The last one comes right
    before SpeechEnded.
    """

    audio: Samples = field(repr=False)


@dataclass(frozen=True)
class SpeechEnded:
    audio: Samples = field(repr=False)
    # Frames scored as speech, without pauses and pre-roll
    speech_ms: int


EndpointEvent = SpeechStarted | SpeechAudio | SpeechEnded


def _frames(milliseconds: int) -> int:
    return max(1, -(-milliseconds // FRAME_MS))


class Endpointer:
    """Cuts a continuous 16 kHz PCM16 stream into utterances.

    Feed it the microphone bytes in any chunk size; it reports when speech
    starts and hands out each finished utterance with its audio.
    """

    def __init__(
        self, probability: SpeechProbability, settings: EndpointerSettings
    ) -> None:
        self._probability = probability
        self._settings = settings
        self._pending = bytearray()
        self._before: deque[Samples] = deque(
            maxlen=_frames(settings.pre_roll_ms) + _frames(settings.start_ms)
        )
        self._speech_run = 0
        self._utterance: list[Samples] | None = None
        # Frames of the utterance not yet handed out as SpeechAudio
        self._fresh: list[Samples] = []
        self._speech_frames = 0
        self._silent_frames = 0

    @property
    def active(self) -> bool:
        """Whether an utterance has started and not ended yet."""
        return self._utterance is not None

    @property
    def speech_ms(self) -> int:
        """Speech in the current utterance so far; 0 outside of one."""
        return self._speech_frames * FRAME_MS if self._utterance is not None else 0

    def reset(self) -> None:
        """Forget a partial utterance, e.g. when the caller mutes."""
        self._pending.clear()
        self._before.clear()
        self._speech_run = 0
        self._utterance = None
        self._fresh = []

    def feed(self, pcm: bytes) -> list[EndpointEvent]:
        self._pending.extend(pcm)
        frame_bytes = FRAME_SAMPLES * 2
        events: list[EndpointEvent] = []
        while len(self._pending) >= frame_bytes:
            chunk = bytes(self._pending[:frame_bytes])
            del self._pending[:frame_bytes]
            frame = np.frombuffer(chunk, dtype="<i2").astype(np.float32)
            frame /= 32768
            event = self._frame(frame)
            if isinstance(event, SpeechEnded):
                events.extend(self._take_fresh())
            if event is not None:
                events.append(event)
        events.extend(self._take_fresh())
        return events

    def _take_fresh(self) -> list[SpeechAudio]:
        if not self._fresh:
            return []
        audio = SpeechAudio(np.concatenate(self._fresh))
        self._fresh = []
        return [audio]

    def _frame(self, frame: Samples) -> EndpointEvent | None:
        settings = self._settings
        probability = self._probability(frame)
        if self._utterance is None:
            self._before.append(frame)
            if probability >= settings.threshold:
                self._speech_run += 1
            elif probability < settings.silence_threshold:
                self._speech_run = 0
            if self._speech_run * FRAME_MS < settings.start_ms:
                return None
            self._utterance = list(self._before)
            self._fresh = list(self._before)
            self._before.clear()
            self._speech_frames = self._speech_run
            self._silent_frames = 0
            self._speech_run = 0
            return SpeechStarted()

        self._utterance.append(frame)
        self._fresh.append(frame)
        if probability >= settings.threshold:
            self._speech_frames += 1
            self._silent_frames = 0
        elif probability < settings.silence_threshold:
            self._silent_frames += 1
        if (
            self._silent_frames * FRAME_MS >= settings.silence_ms
            or len(self._utterance) * FRAME_MS >= settings.max_utterance_ms
        ):
            return self._end()
        return None

    def _end(self) -> SpeechEnded:
        assert self._utterance is not None
        trailing = max(0, self._silent_frames - _frames(self._settings.tail_ms))
        frames = self._utterance[: len(self._utterance) - trailing]
        ended = SpeechEnded(
            audio=np.concatenate(frames), speech_ms=self._speech_frames * FRAME_MS
        )
        self._utterance = None
        return ended
