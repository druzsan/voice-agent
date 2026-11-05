# faster-whisper ships without type information
# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false

from pathlib import Path
from statistics import fmean

import anyio
from anyio import to_thread
from faster_whisper import WhisperModel

from voice_agent.speech.audio import SAMPLE_RATE
from voice_agent.speech.ports import Samples, Transcript


class FasterWhisperRecognizer:
    """English speech recognition with faster-whisper, on the CPU."""

    def __init__(self, model_dir: Path, beam_size: int) -> None:
        self._model = WhisperModel(str(model_dir), device="cpu", compute_type="int8")
        self._beam_size = beam_size
        # One recognition at a time; parallel runs would only compete for the cores
        self._limiter = anyio.CapacityLimiter(1)

    async def transcribe(self, samples: Samples) -> Transcript:
        return await to_thread.run_sync(
            self._transcribe, samples, limiter=self._limiter
        )

    def _transcribe(self, samples: Samples) -> Transcript:
        segments, _ = self._model.transcribe(
            samples,
            language="en",
            beam_size=self._beam_size,
            # Trims the silence before and after the caller's words
            vad_filter=True,
            condition_on_previous_text=False,
            without_timestamps=True,
        )
        recognized = list(segments)
        return Transcript(
            text=" ".join(segment.text.strip() for segment in recognized).strip(),
            audio_ms=round(len(samples) / SAMPLE_RATE * 1000),
            avg_logprob=fmean(s.avg_logprob for s in recognized)
            if recognized
            else None,
            no_speech_prob=fmean(s.no_speech_prob for s in recognized)
            if recognized
            else None,
        )
