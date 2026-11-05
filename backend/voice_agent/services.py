"""The app's long-lived parts, built once at startup."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Annotated

from anyio import to_thread
from fastapi import Depends, Request

from voice_agent.config import Settings
from voice_agent.conversation.records import CallSetup
from voice_agent.conversation.repository import ConversationRepository
from voice_agent.conversation.turns import TurnService
from voice_agent.db.repository import SqlConversationRepository, create_engine
from voice_agent.llm.providers import build_model
from voice_agent.llm.responder import Responder
from voice_agent.speech.model_files import (
    ensure_models,
    piper_voice_file,
    whisper_dir,
)
from voice_agent.speech.ports import SpeechRecognizer, SpeechSynthesizer

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Services:
    settings: Settings
    repository: ConversationRepository
    recognizer: SpeechRecognizer
    synthesizer: SpeechSynthesizer
    responder: Responder

    def turns(self) -> TurnService:
        settings = self.settings
        return TurnService(
            repository=self.repository,
            recognizer=self.recognizer,
            synthesizer=self.synthesizer,
            responder=self.responder,
            setup=CallSetup(
                llm_provider=settings.llm_provider,
                llm_model=settings.llm_model
                if settings.llm_provider != "echo"
                else None,
                stt_model=settings.stt_model,
                tts_voice=settings.tts_voice,
            ),
            history_messages=settings.llm_history_messages,
            max_recording_s=settings.max_recording_s,
        )


def build_responder(settings: Settings) -> Responder:
    return Responder(
        build_model(settings), settings.llm_timeout_s, settings.llm_max_tokens
    )


@asynccontextmanager
async def production_services(settings: Settings) -> AsyncGenerator[Services]:
    # Imported here, so tests with fake speech never load the speech libraries
    from voice_agent.speech.piper import PiperSynthesizer
    from voice_agent.speech.whisper import FasterWhisperRecognizer

    # Downloads only what's missing; the first start takes a while
    await to_thread.run_sync(
        ensure_models, settings.models_dir, settings.stt_model, settings.tts_voice
    )
    engine = create_engine(settings.database_url.get_secret_value())
    try:
        recognizer = FasterWhisperRecognizer(
            whisper_dir(settings.models_dir, settings.stt_model),
            beam_size=settings.stt_beam_size,
        )
        synthesizer = PiperSynthesizer(
            piper_voice_file(settings.models_dir, settings.tts_voice)
        )
        services = Services(
            settings=settings,
            repository=SqlConversationRepository(engine),
            recognizer=recognizer,
            synthesizer=synthesizer,
            responder=build_responder(settings),
        )
        await warm_up(services)
        yield services
    finally:
        await engine.dispose()


async def warm_up(services: Services) -> None:
    """Run each speech model once, so the first call doesn't pay for it."""
    import numpy as np

    await services.synthesizer.synthesize("Hello.")
    await services.recognizer.transcribe(np.zeros(16_000, dtype=np.float32))
    logger.info("Speech models are ready")


def get_services(request: Request) -> Services:
    services: Services = request.app.state.services
    return services


def get_turns(request: Request) -> TurnService:
    turns: TurnService = request.app.state.turns
    return turns


ServicesDep = Annotated[Services, Depends(get_services)]
TurnsDep = Annotated[TurnService, Depends(get_turns)]
