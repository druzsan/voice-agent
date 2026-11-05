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
    model: str
    # The browser stops recording here; longer recordings are refused
    max_recording_s: float


class TtsStatus(BaseModel):
    model: str


class StatusResponse(BaseModel):
    database: Literal["ok", "error"]
    llm: LlmStatus
    stt: SttStatus
    tts: TtsStatus


@router.get("/status")
async def status(services: ServicesDep) -> StatusResponse:
    """What the app runs with, and whether the database is reachable."""
    settings = services.settings
    return StatusResponse(
        database="ok" if await services.repository.ping() else "error",
        llm=LlmStatus(
            provider=settings.llm_provider,
            model=settings.llm_model if settings.llm_provider != "echo" else None,
            configured=services.responder.configured,
        ),
        stt=SttStatus(
            model=settings.stt_model, max_recording_s=settings.max_recording_s
        ),
        tts=TtsStatus(model=settings.tts_voice),
    )
