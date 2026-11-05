"""The assembled app with in-memory storage and fake speech: no database, no containers."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from tests.fakes import (
    FakeRecognizer,
    FakeSynthesizer,
    FakeVad,
    InMemoryConversationRepository,
)
from voice_agent.config import Settings
from voice_agent.llm.providers import echo_model
from voice_agent.llm.responder import Responder
from voice_agent.main import create_app
from voice_agent.services import Services


@pytest.fixture
def repository() -> InMemoryConversationRepository:
    return InMemoryConversationRepository()


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        llm_provider="echo",
        max_recording_s=5,
    )


@pytest.fixture
def recognizer() -> FakeRecognizer:
    return FakeRecognizer()


@pytest.fixture
def synthesizer() -> FakeSynthesizer:
    return FakeSynthesizer()


@pytest.fixture
def responder() -> Responder:
    return Responder(echo_model(), timeout_s=5, max_tokens=100)


@pytest.fixture
def services(
    settings: Settings,
    repository: InMemoryConversationRepository,
    recognizer: FakeRecognizer,
    synthesizer: FakeSynthesizer,
    responder: Responder,
) -> Services:
    return Services(
        settings=settings,
        repository=repository,
        recognizer=recognizer,
        synthesizer=synthesizer,
        responder=responder,
        vad=FakeVad(),
    )


@pytest.fixture
def client(services: Services) -> Iterator[TestClient]:
    with TestClient(create_app(services=services)) as client:
        yield client
