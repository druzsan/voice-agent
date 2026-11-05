"""The app's long-lived parts, built once at startup."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Annotated

from anyio import to_thread
from fastapi import Depends, Request
from openai import AsyncOpenAI

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
from voice_agent.speech.audio import synthesize_clip
from voice_agent.speech.model_files import (
    ensure_models,
    piper_voice_file,
    whisper_dir,
)
from voice_agent.speech.openai_live import OpenAILiveRecognizer
from voice_agent.speech.openai_speech import (
    OpenAIRecognizer,
    OpenAISynthesizer,
    openai_client,
)
from voice_agent.speech.ports import (
    LiveRecognizer,
    SpeechRecognizer,
    SpeechSynthesizer,
)
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
    # Recognizes live calls while the caller speaks; None: after each utterance
    live_recognizer: LiveRecognizer | None = None

    def _setup(self, *, live: bool = False) -> CallSetup:
        settings = self.settings
        return CallSetup(
            llm_provider=settings.llm_provider,
            llm_model=settings.llm_model if settings.llm_provider != "echo" else None,
            stt_model=settings.stt_name(live=live and self.live_recognizer is not None),
            tts_voice=settings.tts_name(),
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
            live_recognizer=self.live_recognizer,
            synthesizer=self.synthesizer,
            responder=self.responder,
            vad=self.vad,
            setup=self._setup(live=True),
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
    local_stt = settings.stt_provider == "local"
    local_tts = settings.tts_provider == "local"
    # Downloads only what's missing; the first start takes a while
    await to_thread.run_sync(
        ensure_models,
        settings.models_dir,
        settings.stt_model if local_stt else None,
        settings.tts_voice if local_tts else None,
    )
    engine = create_engine(settings.database_url.get_secret_value())
    openai = _openai_client(settings)
    try:
        recognizer, live_recognizer = _build_recognizers(settings, openai)
        services = Services(
            settings=settings,
            repository=SqlConversationRepository(engine),
            recognizer=recognizer,
            live_recognizer=live_recognizer,
            synthesizer=_build_synthesizer(settings, openai),
            responder=build_responder(settings),
            vad=SileroVad(),
        )
        await warm_up(services, recognizer=local_stt, synthesizer=local_tts)
        yield services
    finally:
        if openai is not None:
            await openai.close()
        await engine.dispose()


def _openai_client(settings: Settings) -> AsyncOpenAI | None:
    """The client for OpenAI speech, when a speech provider is openai."""
    if "openai" not in (settings.stt_provider, settings.tts_provider):
        return None
    if settings.openai_api_key is None:
        raise RuntimeError("STT_PROVIDER or TTS_PROVIDER is openai: set OPENAI_API_KEY")
    return openai_client(
        settings.openai_api_key.get_secret_value(),
        settings.openai_base_url,
        settings.openai_timeout_s,
    )


def _build_recognizers(
    settings: Settings, openai: AsyncOpenAI | None
) -> tuple[SpeechRecognizer, LiveRecognizer | None]:
    if settings.stt_provider == "local":
        # Imported here, so tests with fake speech never load the speech libraries
        from voice_agent.speech.whisper import FasterWhisperRecognizer

        recognizer = FasterWhisperRecognizer(
            whisper_dir(settings.models_dir, settings.stt_model),
            beam_size=settings.stt_beam_size,
        )
        return recognizer, None
    assert openai is not None
    live = (
        OpenAILiveRecognizer(
            openai, settings.openai_live_stt_model, settings.openai_timeout_s
        )
        if settings.uses_live_stt
        else None
    )
    return OpenAIRecognizer(openai, settings.openai_stt_model), live


def _build_synthesizer(
    settings: Settings, openai: AsyncOpenAI | None
) -> SpeechSynthesizer:
    if settings.tts_provider == "local":
        from voice_agent.speech.piper import PiperSynthesizer

        return PiperSynthesizer(
            piper_voice_file(settings.models_dir, settings.tts_voice)
        )
    assert openai is not None
    return OpenAISynthesizer(
        openai,
        settings.openai_tts_model,
        settings.openai_tts_voice,
        settings.openai_tts_instructions,
        settings.openai_tts_speed,
    )


async def warm_up(
    services: Services, *, recognizer: bool = True, synthesizer: bool = True
) -> None:
    """Run each local speech model once, so the first call doesn't pay for it.

    Hosted models are skipped: a request costs money and warms nothing here.
    """
    import numpy as np

    if synthesizer:
        await synthesize_clip(services.synthesizer, "Hello.")
    if recognizer:
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
