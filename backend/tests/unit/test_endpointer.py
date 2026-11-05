from collections.abc import Iterator

import numpy as np

from voice_agent.speech.ports import Samples
from voice_agent.speech.vad import (
    FRAME_MS,
    FRAME_SAMPLES,
    Endpointer,
    EndpointerSettings,
    EndpointEvent,
    SpeechAudio,
    SpeechEnded,
    SpeechStarted,
)

SETTINGS = EndpointerSettings(
    start_ms=160, silence_ms=320, pre_roll_ms=96, tail_ms=64, max_utterance_ms=3200
)


def scripted(probabilities: list[float]) -> tuple[Endpointer, bytes]:
    """An endpointer whose voice detection reads the scores from a script.

    Each frame's first sample is its number, so the audio shows which
    frames an utterance kept.
    """
    scores: Iterator[float] = iter(probabilities)

    def probability(frame: Samples) -> float:
        return next(scores)

    frames = np.zeros((len(probabilities), FRAME_SAMPLES), dtype="<i2")
    frames[:, 0] = np.arange(len(probabilities))
    return Endpointer(probability, SETTINGS), frames.tobytes()


def kinds(events: list[EndpointEvent]) -> list[type]:
    """The events without the audio handed out along the way."""
    return [type(event) for event in events if not isinstance(event, SpeechAudio)]


def ended(events: list[EndpointEvent]) -> SpeechEnded:
    assert kinds(events) == [SpeechStarted, SpeechEnded]
    assert isinstance(events[-1], SpeechEnded)
    return events[-1]


def frame_numbers(audio: Samples) -> list[int]:
    return [round(value * 32768) for value in audio[::FRAME_SAMPLES]]


def test_an_utterance_starts_after_a_run_of_speech_and_ends_after_a_pause() -> None:
    # 5 frames silence, 10 speech, 12 silence
    endpointer, audio = scripted([0.0] * 5 + [0.9] * 10 + [0.0] * 12)

    utterance = ended(endpointer.feed(audio))

    assert utterance.speech_ms == 10 * FRAME_MS
    # Pre-roll (3 frames) + speech + tail (2 frames) of silence
    assert frame_numbers(utterance.audio) == list(range(2, 17))


def test_a_short_sound_doesnt_start_an_utterance() -> None:
    endpointer, audio = scripted([0.9] * 4 + [0.0] * 20)

    assert endpointer.feed(audio) == []


def test_wavering_scores_between_the_thresholds_change_nothing() -> None:
    # Speech, then scores between silence (0.35) and speech (0.5)
    endpointer, audio = scripted([0.9] * 6 + [0.4] * 20 + [0.0] * 10)

    utterance = ended(endpointer.feed(audio))

    assert len(utterance.audio) // FRAME_SAMPLES > 26


def test_a_short_pause_doesnt_end_the_utterance() -> None:
    endpointer, audio = scripted([0.9] * 6 + [0.0] * 5 + [0.9] * 6 + [0.0] * 10)

    assert ended(endpointer.feed(audio)).speech_ms == 12 * FRAME_MS


def test_a_long_utterance_ends_without_a_pause() -> None:
    endpointer, audio = scripted([0.9] * 120)

    events = endpointer.feed(audio)

    assert kinds(events) == [SpeechStarted, SpeechEnded, SpeechStarted]


def test_speech_so_far_is_known_while_the_caller_talks() -> None:
    endpointer, audio = scripted([0.9] * 8)
    frame = FRAME_SAMPLES * 2

    endpointer.feed(audio[: 4 * frame])
    assert (endpointer.active, endpointer.speech_ms) == (False, 0)
    endpointer.feed(audio[4 * frame : 5 * frame + 100])
    assert (endpointer.active, endpointer.speech_ms) == (True, 5 * FRAME_MS)
    # Chunks of any size; the rest of a frame waits for more audio
    endpointer.feed(audio[5 * frame + 100 :])
    assert endpointer.speech_ms == 8 * FRAME_MS

    endpointer.reset()
    assert (endpointer.active, endpointer.speech_ms) == (False, 0)


def test_the_audio_is_handed_out_while_the_caller_talks() -> None:
    endpointer, audio = scripted([0.0] * 5 + [0.9] * 10 + [0.0] * 12)
    frame = FRAME_SAMPLES * 2

    # Up to the start, then frame by frame
    events = endpointer.feed(audio[: 10 * frame])
    for start in range(10 * frame, len(audio), frame):
        events += endpointer.feed(audio[start : start + frame])

    assert type(events[0]) is SpeechStarted
    pieces = [event.audio for event in events if isinstance(event, SpeechAudio)]
    # The last piece comes before the end
    assert isinstance(events[-2], SpeechAudio)
    assert isinstance(events[-1], SpeechEnded)
    # Pre-roll included; unlike the ended utterance, nothing is trimmed
    assert frame_numbers(pieces[0]) == list(range(2, 10))
    # Up to the end of the pause (10 frames)
    assert frame_numbers(np.concatenate(pieces)) == list(range(2, 25))


def test_no_audio_is_handed_out_outside_of_an_utterance() -> None:
    endpointer, audio = scripted([0.9] * 4 + [0.0] * 20)

    assert endpointer.feed(audio) == []

    endpointer, audio = scripted([0.9] * 8)
    endpointer.feed(audio)
    endpointer.reset()
    assert endpointer.feed(b"") == []
