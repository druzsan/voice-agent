"""Live calls over WS /api/call, with fake voice detection and speech models."""

import base64
import threading
import time
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import replace
from typing import Any

import anyio
import pytest
from fastapi.testclient import TestClient
from pydantic_ai.messages import ModelMessage, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from starlette.testclient import WebSocketTestSession
from starlette.websockets import WebSocketDisconnect

from tests.fakes import (
    FakeLiveRecognizer,
    FakeRecognizer,
    FakeSynthesizer,
    InMemoryConversationRepository,
    pcm,
)
from voice_agent.config import Settings
from voice_agent.llm.prompts import GREETING, LLM_FAILED
from voice_agent.llm.responder import Responder
from voice_agent.main import create_app
from voice_agent.services import Services

Received = dict[str, Any]


class Caller:
    """The browser's side of a call: reads messages, acknowledges clips."""

    def __init__(self, ws: WebSocketTestSession) -> None:
        self.ws = ws
        self.received: list[Received] = []

    def next(self) -> Received:
        message: Received = self.ws.receive_json()
        self.received.append(message)
        return message

    def until(
        self, type_: str, *, play: bool = True, **fields: object
    ) -> list[Received]:
        """Messages up to the first of `type_` with `fields`; plays clips on the way."""
        seen: list[Received] = []
        while True:
            message = self.next()
            seen.append(message)
            if message["type"] == "audio_end" and play:
                self.played(message["clip"])
            if message["type"] == type_ and all(
                message.get(key) == value for key, value in fields.items()
            ):
                return seen

    def played(self, clip: int) -> None:
        self.ws.send_json({"type": "played", "clip": clip})

    def say(self, text: str, via: str = "keyboard") -> None:
        self.ws.send_json({"type": "text", "text": text, "via": via})

    def speak(self, seconds: float) -> None:
        """Speech, then the pause that ends the turn."""
        self.ws.send_bytes(pcm(seconds, loud=True))
        self.ws.send_bytes(pcm(1, loud=False))

    def hang_up(self) -> Received:
        self.ws.send_json({"type": "hangup"})
        return self.until("call_ended")[-1]


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        llm_provider="echo",
        max_recording_s=5,
        vad_silence_ms=300,
        barge_in_ms=400,
    )


@pytest.fixture
def connect(client: TestClient) -> Callable[..., Any]:
    def connect(**headers: str) -> Any:
        return client.websocket_connect("/api/call", headers=headers)

    return connect


@pytest.fixture
def caller(connect: Callable[..., Any]) -> Iterator[Caller]:
    with connect() as ws:
        caller = Caller(ws)
        # The greeting has played
        caller.until("state", state="listening")
        yield caller


def stored(repository: InMemoryConversationRepository) -> list[tuple[str, str]]:
    return [(m.source, m.text) for m in repository.messages]


def wait_for(condition: Callable[[], bool]) -> None:
    """For what the server still does after the test's side closed."""
    deadline = time.monotonic() + 5
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.01)


def test_the_call_starts_with_the_spoken_greeting(
    connect: Callable[..., Any], repository: InMemoryConversationRepository
) -> None:
    with connect() as ws:
        caller = Caller(ws)
        started = caller.next()
        greeting = caller.until("state", state="listening")

    types = [m["type"] for m in greeting]
    assert started["type"] == "call_started"
    assert types.index("state") < types.index("audio")
    assert greeting[0] == {"type": "assistant_delta", "turn": 1, "text": GREETING}
    clips = [m for m in greeting if m["type"] == "audio_end"]
    assert " ".join(c["text"] for c in clips) == GREETING
    # Each clip in pieces as it's synthesized, then its end
    first = [m for m in greeting if m.get("clip") == clips[0]["clip"]]
    assert [m["type"] for m in first] == ["audio", "audio", "audio_end"]
    assert first[0]["sample_rate"] == 16_000
    assert base64.b64decode(first[0]["pcm_base64"]) == bytes(1600)
    assert first[-1]["duration_ms"] == 100
    final = next(m for m in greeting if m["type"] == "assistant_message")
    assert final["source"] == "template" and final["interrupted"] is False
    assert stored(repository)[0] == ("template", GREETING)


def test_a_typed_message_is_answered_as_it_streams(
    caller: Caller, repository: InMemoryConversationRepository
) -> None:
    caller.say("Hello there", via="keypad")
    turn = caller.until("turn_done")
    turn += caller.until("state", state="listening")

    user = next(m for m in turn if m["type"] == "user_message")
    assert user["text"] == "Hello there" and user["source"] == "keypad"
    deltas = [m["text"] for m in turn if m["type"] == "assistant_delta"]
    assert len(deltas) > 1
    assert "".join(deltas).strip() == "You said: Hello there"
    states = [m["state"] for m in turn if m["type"] == "state"]
    assert states == ["thinking", "speaking", "listening"]
    final = next(m for m in turn if m["type"] == "assistant_message")
    assert final["text"] == "You said: Hello there"
    timings = next(m for m in turn if m["type"] == "turn_done")["timings_ms"]
    assert {"llm_first_token", "llm_total", "first_audio", "total"} <= set(timings)
    assert stored(repository)[1:] == [
        ("keypad", "Hello there"),
        ("llm", "You said: Hello there"),
    ]


def test_speech_is_answered_when_the_caller_pauses(
    caller: Caller, recognizer: FakeRecognizer
) -> None:
    caller.speak(1)
    turn = caller.until("turn_done")

    assert [m["active"] for m in turn if m["type"] == "caller_speech"] == [True, False]
    user = next(m for m in turn if m["type"] == "user_message")
    assert user["source"] == "voice" and user["text"] == "What time is it?"
    # The utterance with a little pre-roll and pause, no silence trimming
    assert 1.0 <= len(recognizer.heard[0]) / 16_000 < 1.6
    assert recognizer.trimmed == [False]
    assert "stt" in turn[-1]["timings_ms"]


def test_talking_over_the_reply_interrupts_it(
    services: Services,
    connect: Callable[..., Any],
    repository: InMemoryConversationRepository,
) -> None:
    with connect() as ws:
        caller = Caller(ws)
        caller.until("state", state="listening")
        caller.say("Tell me a story. Make it long.")
        # The first sentence plays, the rest doesn't
        first = caller.until("audio_end", play=False)[-1]
        caller.played(first["clip"])
        ws.send_bytes(pcm(0.6, loud=True))
        interrupted = caller.until("interrupted")
        rest = caller.until("assistant_message")
        ws.send_bytes(pcm(1, loud=False))
        next_turn = caller.until("user_message")

    assert interrupted[-1]["turn"] == first["turn"]
    assert rest[-1]["interrupted"] is True
    reply = repository.messages[2]
    assert reply.interrupted
    assert reply.heard_text == first["text"]
    assert any(m["type"] == "user_message" for m in next_turn)


def test_a_short_sound_over_the_reply_doesnt_interrupt_it(
    caller: Caller, repository: InMemoryConversationRepository
) -> None:
    caller.say("Tell me a story. Make it long.")
    caller.until("audio_end", play=False)
    caller.ws.send_bytes(pcm(0.2, loud=True) + pcm(1, loud=False))
    turn = caller.until("turn_done")

    assert not any(m["type"] == "interrupted" for m in turn)
    # Nothing was answered: the sound was ignored
    assert [m.role for m in repository.messages] == ["assistant", "user", "assistant"]
    assert repository.messages[-1].interrupted is False


def test_hanging_up_ends_the_call(
    caller: Caller, repository: InMemoryConversationRepository
) -> None:
    assert caller.hang_up() == {"type": "call_ended", "reason": "hangup"}

    conversation = next(iter(repository.conversations.values()))
    assert conversation.end_reason == "hangup" and conversation.ended_at is not None


def slow_story() -> tuple[FunctionModel, threading.Event]:
    """A model that says one sentence, then waits until released."""
    release = threading.Event()

    async def stream(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str]:
        yield "Once upon a time. "
        while not release.is_set():
            await anyio.sleep(0.01)
        yield "The end."

    return FunctionModel(stream_function=stream), release


def test_disconnecting_mid_reply_stores_what_was_said(
    services: Services, repository: InMemoryConversationRepository
) -> None:
    model, release = slow_story()
    app = create_app(services=replace(services, responder=Responder(model, 5, 100)))
    with TestClient(app) as client:
        with client.websocket_connect("/api/call") as ws:
            caller = Caller(ws)
            caller.until("state", state="listening")
            caller.say("Tell me a story. Make it long.")
            caller.until("audio")
        # The browser is gone while the model still writes
        wait_for(
            lambda: next(iter(repository.conversations.values())).ended_at is not None
        )
        release.set()

    conversation = next(iter(repository.conversations.values()))
    assert conversation.end_reason == "disconnect"
    reply = repository.messages[-1]
    assert (reply.text, reply.interrupted) == ("Once upon a time.", True)


def test_a_model_failing_midway_keeps_the_spoken_part(
    services: Services, repository: InMemoryConversationRepository
) -> None:
    async def stream(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str]:
        yield "Let me think. "
        raise RuntimeError("provider down")

    model = FunctionModel(stream_function=stream)
    app = create_app(services=replace(services, responder=Responder(model, 5, 100)))
    with TestClient(app) as client, client.websocket_connect("/api/call") as ws:
        caller = Caller(ws)
        caller.until("state", state="listening")
        caller.say("Hello")
        turn = caller.until("turn_done")

    finals = [m for m in turn if m["type"] == "assistant_message"]
    assert [(m["text"], m["source"], m["interrupted"]) for m in finals] == [
        ("Let me think.", "llm", True),
        (LLM_FAILED, "template", False),
    ]
    assert stored(repository)[-2:] == [
        ("llm", "Let me think."),
        ("template", LLM_FAILED),
    ]


def test_the_next_prompt_says_what_the_caller_heard(
    services: Services, repository: InMemoryConversationRepository
) -> None:
    prompts: list[list[str]] = []

    async def stream(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str]:
        prompts.append(
            [
                part.content
                for part in messages[-1].parts
                if isinstance(part, UserPromptPart) and isinstance(part.content, str)
            ]
        )
        yield "First sentence. Second sentence. Third sentence."

    model = FunctionModel(stream_function=stream)
    app = create_app(services=replace(services, responder=Responder(model, 5, 100)))
    with TestClient(app) as client, client.websocket_connect("/api/call") as ws:
        caller = Caller(ws)
        caller.until("state", state="listening")
        caller.say("Talk")
        first = caller.until("audio_end", play=False)[-1]
        caller.played(first["clip"])
        ws.send_bytes(pcm(0.6, loud=True))
        caller.until("assistant_message")
        caller.say("Sorry, go on")
        caller.until("turn_done")

    assert prompts[1] == [
        "(You were interrupted. The caller heard only: 'First sentence.')",
        "Sorry, go on",
    ]


def test_a_lost_played_message_doesnt_hold_the_call(caller: Caller) -> None:
    caller.say("Hello")
    # The clips are never acknowledged; playback counts as over after their
    # length plus a grace period
    turn = caller.until("state", play=False, state="listening")

    assert any(m["type"] == "assistant_message" for m in turn)


def test_the_call_ends_at_its_time_limit(
    services: Services, repository: InMemoryConversationRepository
) -> None:
    settings = services.settings.model_copy(update={"max_call_s": 0.5})
    app = create_app(services=replace(services, settings=settings))
    with TestClient(app) as client, client.websocket_connect("/api/call") as ws:
        ended = Caller(ws).until("call_ended")[-1]

    assert ended["reason"] == "timeout"
    assert next(iter(repository.conversations.values())).end_reason == "timeout"


def test_a_failing_recognition_is_reported_and_the_call_goes_on(
    caller: Caller, recognizer: FakeRecognizer
) -> None:
    recognizer.fail = True
    caller.speak(1)
    error = caller.until("error")[-1]
    recognizer.fail = False
    caller.say("Still there?")

    assert error["code"] == "stt_failed"
    assert caller.until("turn_done")


def test_muting_drops_what_was_heard(
    caller: Caller, recognizer: FakeRecognizer
) -> None:
    caller.ws.send_bytes(pcm(0.5, loud=True))
    caller.ws.send_json({"type": "mute", "muted": True})
    caller.ws.send_bytes(pcm(1, loud=True))
    caller.ws.send_json({"type": "mute", "muted": False})
    caller.ws.send_bytes(pcm(1, loud=False))
    caller.say("Typed")
    turn = caller.until("turn_done")

    assert recognizer.heard == []
    assert [m["text"] for m in turn if m["type"] == "user_message"] == ["Typed"]


def test_invalid_messages_are_reported(caller: Caller) -> None:
    caller.ws.send_text("not json")
    caller.ws.send_json({"type": "text", "text": ""})

    assert [caller.until("error")[-1]["code"] for _ in range(2)] == [
        "invalid_message",
        "invalid_message",
    ]


def test_an_oversized_audio_frame_closes_the_call(
    caller: Caller, repository: InMemoryConversationRepository
) -> None:
    caller.ws.send_bytes(b"\0" * (64 * 1024 + 2))

    with pytest.raises(WebSocketDisconnect) as closed:
        caller.until("never")
    assert closed.value.code == 1009
    wait_for(lambda: next(iter(repository.conversations.values())).ended_at is not None)
    assert next(iter(repository.conversations.values())).end_reason == "error"


def test_other_sites_cant_place_calls(connect: Callable[..., Any]) -> None:
    with (
        pytest.raises(WebSocketDisconnect) as refused,
        connect(origin="https://evil.example"),
    ):
        pass

    assert refused.value.code == 1008


def test_pages_of_this_app_can(connect: Callable[..., Any]) -> None:
    with connect(origin="http://testserver") as ws:
        assert ws.receive_json()["type"] == "call_started"


def test_without_storage_the_call_doesnt_start(
    connect: Callable[..., Any], repository: InMemoryConversationRepository
) -> None:
    async def unavailable(*args: object) -> None:
        raise ConnectionError("database down")

    repository.create_conversation = unavailable  # type: ignore[method-assign]

    with connect() as ws, pytest.raises(WebSocketDisconnect) as closed:
        ws.receive_json()
    assert closed.value.code == 1011


def test_without_voice_the_reply_is_still_shown(
    caller: Caller, synthesizer: FakeSynthesizer
) -> None:
    synthesizer.fail = True
    caller.say("Hello")
    turn = caller.until("turn_done")

    assert not any(m["type"] == "audio" for m in turn)
    assert any(m["type"] == "assistant_message" for m in turn)


def test_messages_during_a_turn_are_answered_after_it(
    services: Services, repository: InMemoryConversationRepository
) -> None:
    model, release = slow_story()
    app = create_app(services=replace(services, responder=Responder(model, 5, 100)))
    with TestClient(app) as client, client.websocket_connect("/api/call") as ws:
        caller = Caller(ws)
        caller.until("state", state="listening")
        caller.say("First")
        caller.until("audio")
        caller.say("Second")
        release.set()
        caller.until("turn_done", turn=2)
        caller.until("turn_done", turn=3)

    assert [m.text for m in repository.messages[1:]] == [
        "First",
        "Once upon a time. The end.",
        "Second",
        "Once upon a time. The end.",
    ]


@pytest.fixture
def live() -> FakeLiveRecognizer:
    return FakeLiveRecognizer()


@pytest.fixture
def live_caller(services: Services, live: FakeLiveRecognizer) -> Iterator[Caller]:
    app = create_app(services=replace(services, live_recognizer=live))
    with TestClient(app) as client, client.websocket_connect("/api/call") as ws:
        caller = Caller(ws)
        caller.until("state", state="listening")
        yield caller


def test_live_recognition_hears_the_caller_while_they_speak(
    live_caller: Caller,
    live: FakeLiveRecognizer,
    recognizer: FakeRecognizer,
    repository: InMemoryConversationRepository,
) -> None:
    live.session.texts = ["Is my car ready?"]
    live_caller.speak(1)
    turn = live_caller.until("turn_done")

    user = next(m for m in turn if m["type"] == "user_message")
    assert user["text"] == "Is my car ready?"
    assert live.session.calls == ["append", "commit"]
    # Pre-roll, speech and the pause went to the live session
    assert recognizer.heard == []
    assert live.session.opened == 1
    stored_user = repository.messages[1]
    assert stored_user.stt is not None and stored_user.stt["audio_ms"] >= 1000
    conversation = next(iter(repository.conversations.values()))
    assert conversation.stt_model == "small.en"


def test_a_failing_live_recognition_falls_back_to_the_recording(
    live_caller: Caller, live: FakeLiveRecognizer, recognizer: FakeRecognizer
) -> None:
    live.session.fail = True
    live_caller.speak(1)
    turn = live_caller.until("turn_done")

    user = next(m for m in turn if m["type"] == "user_message")
    assert user["text"] == "What time is it?"
    assert len(recognizer.heard) == 1


def test_ignored_speech_is_dropped_from_the_live_session(
    live_caller: Caller, live: FakeLiveRecognizer
) -> None:
    live_caller.say("Tell me a story. Make it long.")
    live_caller.until("audio_end", play=False)
    live_caller.ws.send_bytes(pcm(0.2, loud=True) + pcm(1, loud=False))
    live_caller.until("turn_done")

    assert live.session.calls == ["append", "clear"]


def test_muting_drops_the_live_audio(
    live_caller: Caller, live: FakeLiveRecognizer
) -> None:
    live_caller.ws.send_bytes(pcm(0.5, loud=True))
    live_caller.until("caller_speech", active=True)
    live_caller.ws.send_json({"type": "mute", "muted": True})
    live_caller.until("caller_speech", active=False)

    assert live.session.calls == ["append", "clear"]


def test_utterances_answered_together_join_their_live_transcripts(
    services: Services, live: FakeLiveRecognizer
) -> None:
    release = threading.Event()

    async def stream(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str]:
        while not release.is_set():
            await anyio.sleep(0.01)
        yield "Sure."

    model = FunctionModel(stream_function=stream)
    live.session.texts = ["My car is late.", "And it's red."]
    app = create_app(
        services=replace(
            services, responder=Responder(model, 5, 100), live_recognizer=live
        )
    )
    with TestClient(app) as client, client.websocket_connect("/api/call") as ws:
        caller = Caller(ws)
        caller.until("state", state="listening")
        caller.say("First")
        caller.until("state", state="thinking")
        # Two utterances while the model still thinks: answered as one
        caller.speak(0.3)
        caller.until("caller_speech", active=False)
        caller.speak(0.3)
        caller.until("caller_speech", active=False)
        release.set()
        turn = caller.until("turn_done", turn=3)

    user = next(m for m in turn if m["type"] == "user_message")
    assert user["text"] == "My car is late. And it's red."
    assert live.session.calls == ["append", "commit", "append", "commit"]
