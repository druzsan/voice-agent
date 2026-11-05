from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

LlmProvider = Literal["openai", "requesty", "openrouter", "echo"]
# English-only Whisper models; larger ones recognize speech more reliably
# but answer later
WhisperModelName = Literal["tiny.en", "base.en", "small.en", "medium.en"]

# backend/ on the host, /app in the container
BACKEND_DIR = Path(__file__).resolve().parents[1]
# The repository root's .env, for tools started from backend/ on the host.
# In the containers, Compose passes the variables and this file doesn't exist.
ENV_FILE = BACKEND_DIR.parent / ".env"


def _credential(name: str) -> AliasChoices:
    """Read VOICE_AGENT_<name>, falling back to the conventional <name>."""
    return AliasChoices(f"VOICE_AGENT_{name}", name)


class Settings(BaseSettings):
    """App settings, read from environment variables prefixed with VOICE_AGENT_.

    Provider credentials also accept their conventional names without the
    prefix (e.g. OPENAI_API_KEY). See .env.example for descriptions.
    """

    model_config = SettingsConfigDict(
        env_prefix="VOICE_AGENT_",
        env_file=ENV_FILE,
        # `VOICE_AGENT_LLM_MODEL=` in .env means unset, not an empty model ID
        env_ignore_empty=True,
        extra="ignore",
        validate_by_name=True,
    )

    app_name: str = "Voice Agent"
    version: str = "0.1.0"

    # The development database published by `make dev`; Compose sets the URL
    # of its own network for the containers
    database_url: SecretStr = SecretStr(
        "postgresql+psycopg://voice_agent:voice_agent@127.0.0.1:5432/voice_agent"
    )

    llm_provider: LlmProvider = "echo"
    llm_model: str | None = None
    openai_api_key: SecretStr | None = Field(
        default=None, validation_alias=_credential("OPENAI_API_KEY")
    )
    requesty_api_key: SecretStr | None = Field(
        default=None, validation_alias=_credential("REQUESTY_API_KEY")
    )
    requesty_base_url: str = Field(
        default="https://router.requesty.ai/v1",
        validation_alias=_credential("REQUESTY_BASE_URL"),
    )
    openrouter_api_key: SecretStr | None = Field(
        default=None, validation_alias=_credential("OPENROUTER_API_KEY")
    )
    llm_timeout_s: float = Field(default=20, gt=0)
    llm_max_tokens: int = Field(default=1024, gt=0)
    llm_history_messages: int = Field(default=20, ge=0)

    stt_model: WhisperModelName = "small.en"
    stt_beam_size: int = Field(default=1, ge=1)
    max_recording_s: float = Field(default=30, gt=0)
    tts_voice: str = Field(
        default="en_US-lessac-medium", pattern=r"^en_[A-Z]{2}-\w+-\w+$"
    )
    # Speech model files, downloaded here at startup when missing. Compose
    # mounts the host's backend/models, so both use the same files.
    models_dir: Path = BACKEND_DIR / "models"
