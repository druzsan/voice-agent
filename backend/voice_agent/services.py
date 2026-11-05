"""The app's long-lived parts, built once at startup."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Annotated

from anyio import to_thread
from fastapi import Depends, Request

from voice_agent.config import Settings
from voice_agent.conversation.call_session import (
    CallSession,
    CallSettings,
    CallTransport,
)
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
from voice_agent.speech.vad import (
    FRAME_SAMPLES,
    EndpointerSettings,
    SileroVad,
    VoiceActivityDetector,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Services:
    settings: Settings
    repository: ConversationRepository
    recognizer: SpeechRecognizer
    synthesizer: SpeechSynthesizer
    responder: Responder
    vad: VoiceActivityDetector

    def _setup(self) -> CallSetup:
        settings = self.settings
        return CallSetup(
            llm_provider=settings.llm_provider,
            llm_model=settings.llm_model if settings.llm_provider != "echo" else None,
            stt_model=settings.stt_model,
            tts_voice=settings.tts_voice,
        )

    def turns(self) -> TurnService:
        """Push-to-talk conversations over plain HTTP requests."""
        return TurnService(
            repository=self.repository,
            recognizer=self.recognizer,
            synthesizer=self.synthesizer,
            responder=self.responder,
            setup=self._setup(),
            history_messages=self.settings.llm_history_messages,
            max_recording_s=self.settings.max_recording_s,
        )

    def call(self, transport: CallTransport) -> CallSession:
        """A live call over `transport`."""
        settings = self.settings
        return CallSession(
            transport=transport,
            repository=self.repository,
            recognizer=self.recognizer,
            synthesizer=self.synthesizer,
            responder=self.responder,
            vad=self.vad,
            setup=self._setup(),
            settings=CallSettings(
                history_messages=settings.llm_history_messages,
                max_call_s=settings.max_call_s,
                barge_in_ms=settings.barge_in_ms,
                endpointer=EndpointerSettings(
                    threshold=settings.vad_threshold,
                    silence_threshold=settings.vad_threshold - 0.15,
                    silence_ms=settings.vad_silence_ms,
                    max_utterance_ms=round(settings.max_recording_s * 1000),
                ),
            ),
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
            vad=SileroVad(),
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
    services.vad.stream()(np.zeros(FRAME_SAMPLES, dtype=np.float32))
    logger.info("Speech models are ready")


def get_services(request: Request) -> Services:
    services: Services = request.app.state.services
    return services


def get_turns(request: Request) -> TurnService:
    turns: TurnService = request.app.state.turns
    return turns


ServicesDep = Annotated[Services, Depends(get_services)]
TurnsDep = Annotated[TurnService, Depends(get_turns)]
