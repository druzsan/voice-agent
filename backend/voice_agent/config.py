from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

LlmProvider = Literal["openai", "requesty", "openrouter", "echo"]
# local: faster-whisper and Piper on the CPU; openai: OpenAI's speech models
SpeechProvider = Literal["local", "openai"]
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
    prefix (e.g. OPENAI_API_KEY). .env.example shows the common ones.
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

    # gpt-6.1-sol on Azure in Germany, through Requesty's EU router. Without
    # REQUESTY_API_KEY the model isn't configured and a fixed reply is spoken;
    # echo repeats the caller and needs no key. Only the selected provider's
    # key is used.
    llm_provider: LlmProvider = "requesty"
    # Model ID as the provider lists it, e.g. gpt-4.1-mini for openai,
    # openai/gpt-4.1-mini for openrouter (always with the upstream provider)
    llm_model: str | None = "azure/gpt-6.1-sol@germanywestcentral"
    openai_api_key: SecretStr | None = Field(
        default=None, validation_alias=_credential("OPENAI_API_KEY")
    )
    # Also for the OpenAI speech models. For Azure OpenAI:
    # https://<resource>.openai.azure.com/openai/v1/ with the Azure key and the
    # deployment names as models
    openai_base_url: str = Field(
        default="https://api.openai.com/v1",
        validation_alias=_credential("OPENAI_BASE_URL"),
    )
    requesty_api_key: SecretStr | None = Field(
        default=None, validation_alias=_credential("REQUESTY_API_KEY")
    )
    requesty_base_url: str = Field(
        default="https://router.eu.requesty.ai/v1",
        validation_alias=_credential("REQUESTY_BASE_URL"),
    )
    openrouter_api_key: SecretStr | None = Field(
        default=None, validation_alias=_credential("OPENROUTER_API_KEY")
    )
    # Seconds for one complete answer, after which a fallback reply is spoken
    llm_timeout_s: float = Field(default=20, gt=0)
    # Upper bound for one answer; reasoning models count their hidden reasoning
    # too, so this leaves room even though spoken answers are short
    llm_max_tokens: int = Field(default=1024, gt=0)
    # Earlier messages sent to the model as conversation history; the call
    # state block carries the verified facts beyond it
    llm_history_messages: int = Field(default=40, ge=0)

    # Customer care: handover routes that report "no colleague available",
    # comma-separated (e.g. roadside_assistance,language_support)
    unavailable_routes: str = ""
    # Dates and times Carrie works with
    timezone: str = "Europe/Berlin"

    # local: faster-whisper and Piper on the CPU, audio stays on this machine;
    # openai: OpenAI's speech models (needs OPENAI_API_KEY with API credit)
    stt_provider: SpeechProvider = "local"
    tts_provider: SpeechProvider = "local"

    # Local Whisper model; larger ones recognize more reliably but answer later
    stt_model: WhisperModelName = "small.en"
    # 1 is greedy decoding, the fastest
    stt_beam_size: int = Field(default=1, ge=1)
    # Longest accepted recording; in a live call, an utterance ends here even
    # without a pause
    max_recording_s: float = Field(default=30, gt=0)
    # Local Piper voice
    tts_voice: str = Field(
        default="en_US-lessac-medium", pattern=r"^en_[A-Z]{2}-\w+-\w+$"
    )

    # OpenAI speech. One request, connecting the live transcription and
    # waiting for one of its transcripts each end after openai_timeout_s.
    openai_timeout_s: float = Field(default=15, gt=0)
    # Transcribes whole recordings: push-to-talk, and live calls when live
    # transcription is off or fails
    openai_stt_model: str = "gpt-4o-mini-transcribe"
    # Live calls stream the caller's speech to the Realtime API while they
    # talk, so the transcript is ready shortly after the pause
    openai_stt_live: bool = True
    openai_live_stt_model: str = "gpt-live-transcribe"
    openai_tts_model: str = "gpt-4o-mini-tts"
    openai_tts_voice: str = "marin"
    openai_tts_instructions: str = (
        "Speak in a friendly, warm tone at a brisk, natural conversational pace, "
        "like an experienced customer service agent on the phone. "
        "No long pauses between sentences."
    )
    # 1.0 is the voice's own pace, which sounds slow on the phone
    openai_tts_speed: float = Field(default=1.25, ge=0.25, le=4.0)

    # Live calls. Speech probability (0-1) from which a 32 ms frame counts as
    # speech: higher ignores more noise, but also quiet speech
    vad_threshold: float = Field(default=0.5, gt=0.15, lt=1)
    # The caller's turn ends after this much silence: shorter answers sooner,
    # but cuts off callers who pause mid-sentence
    vad_silence_ms: int = Field(default=800, ge=100)
    # Speech shorter than this doesn't interrupt a reply ("mhm", coughs, echo)
    barge_in_ms: int = Field(default=400, ge=0)
    # Longest call; it ends with the reason "timeout"
    max_call_s: float = Field(default=900, gt=0)
    # Speech model files, downloaded here at startup when missing. Compose
    # mounts the host's backend/models, so both use the same files.
    models_dir: Path = BACKEND_DIR / "models"

    @property
    def uses_live_stt(self) -> bool:
        return self.stt_provider == "openai" and self.openai_stt_live

    def stt_name(self, *, live: bool = False) -> str:
        """The recognizer a conversation runs with, as stored with it."""
        if self.stt_provider == "local":
            return self.stt_model
        model = (
            self.openai_live_stt_model
            if live and self.openai_stt_live
            else self.openai_stt_model
        )
        return f"openai/{model}"

    def tts_name(self) -> str:
        """The voice a conversation runs with, as stored with it."""
        if self.tts_provider == "local":
            return self.tts_voice
        return f"openai/{self.openai_tts_model}/{self.openai_tts_voice}"

    @property
    def unavailable_route_set(self) -> frozenset[str]:
        return frozenset(
            route.strip()
            for route in self.unavailable_routes.split(",")
            if route.strip()
        )
