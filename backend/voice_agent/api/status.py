from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from voice_agent.services import ServicesDep

router = APIRouter(tags=["status"])


class LlmStatus(BaseModel):
    provider: str
    model: str | None
    configured: bool


class SttStatus(BaseModel):
    provider: str
    # In a live call; push-to-talk may use another (OpenAI: file transcription)
    model: str
    # Push-to-talk, and live calls when live recognition fails; None when
    # it's the same model
    fallback_model: str | None = None
    # The browser stops recording here; longer recordings are refused
    max_recording_s: float


class TtsStatus(BaseModel):
    provider: str
    model: str
    # Speaking pace; None for the local voice
    speed: float | None = None


class StatusResponse(BaseModel):
    database: Literal["ok", "error"]
    # Languages Carrie holds conversations in with these speech models
    languages: list[str]
    llm: LlmStatus
    stt: SttStatus
    tts: TtsStatus


@router.get("/status")
async def status(services: ServicesDep) -> StatusResponse:
    """What the app runs with, and whether the database is reachable."""
    settings = services.settings
    live_model = settings.stt_name(live=services.live_recognizer is not None)
    file_model = settings.stt_name()
    return StatusResponse(
        database="ok" if await services.repository.ping() else "error",
        languages=list(services.carrie.supported_languages),
        llm=LlmStatus(
            provider=settings.llm_provider,
            model=settings.llm_model if settings.llm_provider != "echo" else None,
            configured=services.responder.configured,
        ),
        stt=SttStatus(
            provider=settings.stt_provider,
            model=live_model,
            fallback_model=file_model if file_model != live_model else None,
            max_recording_s=settings.max_recording_s,
        ),
        tts=TtsStatus(
            provider=settings.tts_provider,
            model=settings.tts_name(),
            speed=settings.openai_tts_speed
            if settings.tts_provider == "openai"
            else None,
        ),
    )
