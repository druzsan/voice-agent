from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """App settings, read from environment variables prefixed with VOICE_AGENT_."""

    model_config = SettingsConfigDict(env_prefix="VOICE_AGENT_")

    app_name: str = "Voice Agent"
    version: str = "0.1.0"
