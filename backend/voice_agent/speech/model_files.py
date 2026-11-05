"""Pinned speech model files: where they come from and where they live.

The models live in backend/models (VOICE_AGENT_MODELS_DIR), on the host and,
mounted, in the container. Whatever is missing there is downloaded at
startup at a pinned revision; once everything is there, the app doesn't
contact Hugging Face at all.
"""

# huggingface_hub's signatures mention tqdm without type arguments
# pyright: reportUnknownVariableType=false

import logging
from pathlib import Path

from huggingface_hub import hf_hub_download, snapshot_download

logger = logging.getLogger(__name__)

# Hugging Face commits, so every download gets exactly the same files
WHISPER_REVISIONS = {
    "tiny.en": "0d3d19a32d3338f10357c0889762bd8d64bbdeba",
    "base.en": "3d3d5dee26484f91867d81cb899cfcf72b96be6c",
    "small.en": "d1d751a5f8271d482d14ca55d9e2deeebbae577f",
    "medium.en": "a29b04bd15381511a9af671baec01072039215e3",
}
WHISPER_FILES = ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt")
PIPER_REPO = "rhasspy/piper-voices"
PIPER_REVISION = "e7229f7d33a10e145e109b886d661984201ac3c4"


def whisper_dir(models_dir: Path, model: str) -> Path:
    return models_dir / "whisper" / model


def _piper_path(voice: str) -> str:
    """Repository path of a voice, e.g. en/en_US/lessac/medium/en_US-lessac-medium."""
    locale, name, quality = voice.split("-")
    return f"{locale.split('_')[0]}/{locale}/{name}/{quality}/{voice}"


def piper_voice_file(models_dir: Path, voice: str) -> Path:
    """The voice's .onnx file; its .onnx.json config sits next to it."""
    return models_dir / "piper" / f"{_piper_path(voice)}.onnx"


def _piper_files(voice: str) -> tuple[str, ...]:
    voice_path = _piper_path(voice)
    # The model card names the voice's dataset and its licence
    return (
        f"{voice_path}.onnx",
        f"{voice_path}.onnx.json",
        f"{voice_path.rsplit('/', 1)[0]}/MODEL_CARD",
    )


def ensure_models(
    models_dir: Path, stt_model: str | None, tts_voice: str | None
) -> None:
    """Download whichever of the chosen models' files are missing.

    None skips a model, when its provider isn't local.
    """
    if stt_model is not None:
        _ensure_whisper(models_dir, stt_model)
    if tts_voice is not None:
        _ensure_piper(models_dir, tts_voice)


def _ensure_whisper(models_dir: Path, stt_model: str) -> None:
    whisper = whisper_dir(models_dir, stt_model)
    if not all((whisper / name).exists() for name in WHISPER_FILES):
        logger.info("Downloading the Whisper model %s to %s", stt_model, whisper)
        snapshot_download(
            f"Systran/faster-whisper-{stt_model}",
            revision=WHISPER_REVISIONS[stt_model],
            local_dir=whisper,
            allow_patterns=list(WHISPER_FILES),
        )


def _ensure_piper(models_dir: Path, tts_voice: str) -> None:
    piper = models_dir / "piper"
    for filename in _piper_files(tts_voice):
        if not (piper / filename).exists():
            logger.info("Downloading %s to %s", filename, piper)
            hf_hub_download(
                PIPER_REPO, filename, revision=PIPER_REVISION, local_dir=piper
            )
