import numpy as np
import pytest

from tests.fakes import wav_of_silence
from voice_agent.speech.audio import InvalidAudio, max_wav_bytes, read_wav, write_wav


def test_reads_16_khz_mono_pcm_as_float_samples() -> None:
    pcm = np.array([0, 16384, -32768] * 2000, dtype="<i2").tobytes()

    samples = read_wav(write_wav(pcm, 16_000), max_duration_s=30)

    assert samples.dtype == np.float32
    assert samples[:3].tolist() == [0.0, 0.5, -1.0]


@pytest.mark.parametrize(
    ("wav", "message"),
    [
        (b"RIFF nonsense", "Not a valid WAV file"),
        (wav_of_silence(1, sample_rate=44_100), "Expected 16000 Hz"),
        (wav_of_silence(0.1), "too short"),
        (wav_of_silence(3), "longer than 2 s"),
    ],
)
def test_rejects_other_recordings(wav: bytes, message: str) -> None:
    with pytest.raises(InvalidAudio, match=message):
        read_wav(wav, max_duration_s=2)


def test_the_size_limit_fits_the_longest_recording() -> None:
    assert len(wav_of_silence(2)) == max_wav_bytes(2)
