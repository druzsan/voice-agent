from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel
from pydantic_ai.models.openrouter import OpenRouterModel

from voice_agent.config import LlmProvider, Settings
from voice_agent.conversation.records import Message, Role, Source
from voice_agent.llm.prompts import LLM_NOT_CONFIGURED
from voice_agent.llm.providers import build_model, echo_model
from voice_agent.llm.responder import Responder, StreamedReply, to_model_history

pytestmark = pytest.mark.anyio


def settings(
    provider: LlmProvider, model: str | None = "vendor/some-model", **keys: str
) -> Settings:
    return Settings(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        llm_provider=provider,
        llm_model=model,
        **keys,
    )


@pytest.mark.parametrize(
    ("provider", "key", "model_type"),
    [
        ("openai", "openai_api_key", OpenAIResponsesModel),
        ("requesty", "requesty_api_key", OpenAIChatModel),
        ("openrouter", "openrouter_api_key", OpenRouterModel),
    ],
)
def test_builds_the_configured_provider(
    provider: LlmProvider, key: str, model_type: type
) -> None:
    model = build_model(settings(provider, **{key: "secret"}))

    assert model is not None
    assert isinstance(model, model_type)
    assert model.model_name == "vendor/some-model"


def test_a_model_id_the_provider_rejects_is_not_configured() -> None:
    # OpenRouter needs the upstream provider in the ID, e.g. openai/gpt-5-mini
    assert (
        build_model(settings("openrouter", "gpt-5-mini", openrouter_api_key="k"))
        is None
    )


def test_requesty_uses_its_router() -> None:
    model = build_model(settings("requesty", requesty_api_key="secret"))

    assert isinstance(model, OpenAIChatModel)
    # The EU router by default
    assert model.base_url == "https://router.eu.requesty.ai/v1/"


def test_echo_needs_no_model_or_key() -> None:
    assert isinstance(build_model(settings("echo", model=None)), FunctionModel)


@pytest.mark.parametrize(
    "configured",
    [settings("openai", openai_api_key="secret", model=None), settings("openai")],
    ids=["no-model", "no-key"],
)
def test_without_model_or_key_the_model_is_not_configured(configured: Settings) -> None:
    assert build_model(configured) is None


async def test_an_unconfigured_model_gets_a_fixed_reply() -> None:
    reply = await Responder(None, timeout_s=1, max_tokens=10).reply([], "Hi")

    assert reply.text == LLM_NOT_CONFIGURED
    assert reply.source == "template"


def message(
    role: Role,
    source: Source,
    text: str,
    interrupted: bool = False,
    heard_text: str | None = None,
) -> Message:
    return Message(
        id=1,
        conversation_id=uuid4(),
        created_at=datetime.now(UTC),
        role=role,
        source=source,
        text=text,
        interrupted=interrupted,
        heard_text=heard_text,
    )


def test_history_leaves_out_fixed_texts() -> None:
    history = to_model_history(
        [
            message("assistant", "template", "Hello, how can I help?"),
            message("user", "voice", "Hi"),
            message("assistant", "llm", "Hello!"),
            message("user", "keypad", "123"),
            message("assistant", "template", "Sorry, please try again."),
        ]
    )

    assert [type(m) for m in history] == [ModelRequest, ModelResponse, ModelRequest]


def prompts(history: list[ModelMessage]) -> list[list[str]]:
    return [
        [
            part.content
            for part in message.parts
            if isinstance(part, UserPromptPart) and isinstance(part.content, str)
        ]
        for message in history
        if isinstance(message, ModelRequest)
    ]


def test_after_an_interrupted_reply_the_model_learns_what_was_heard() -> None:
    history = to_model_history(
        [
            message("user", "voice", "Tell me a story"),
            message(
                "assistant",
                "llm",
                "Once upon a time. There was a king.",
                interrupted=True,
                heard_text="Once upon a time.",
            ),
        ],
        "Wait, a short one",
    )

    assert prompts(history) == [
        ["Tell me a story"],
        [
            "(You were interrupted. The caller heard only: 'Once upon a time.')",
            "Wait, a short one",
        ],
    ]


async def collect(responder: Responder) -> tuple[list[str], StreamedReply]:
    deltas: list[str] = []

    async def on_text(delta: str) -> None:
        deltas.append(delta)

    reply = await responder.stream([], "Hi there", on_text)
    return deltas, reply


async def test_a_streamed_reply_arrives_piece_by_piece() -> None:
    deltas, reply = await collect(Responder(echo_model(), timeout_s=1, max_tokens=10))

    assert deltas == ["You ", "said: ", "Hi ", "there "]
    assert (reply.text, reply.source, reply.failed) == (
        "You said: Hi there",
        "llm",
        False,
    )
    assert reply.usage is not None and reply.usage["requests"] == 1
    assert reply.first_token_ms is not None


async def test_a_stream_that_breaks_keeps_its_beginning() -> None:
    async def breaking(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str]:
        yield "Well, "
        raise RuntimeError("provider down")

    _, reply = await collect(Responder(FunctionModel(stream_function=breaking), 1, 10))

    assert (reply.text, reply.failed) == ("Well,", True)


async def test_an_unconfigured_model_streams_a_fixed_reply() -> None:
    deltas, reply = await collect(Responder(None, timeout_s=1, max_tokens=10))

    assert deltas == [LLM_NOT_CONFIGURED]
    assert reply.source == "template"
