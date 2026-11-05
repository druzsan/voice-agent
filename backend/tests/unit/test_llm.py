from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import Model
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel
from pydantic_ai.models.openrouter import OpenRouterModel
from pydantic_ai.usage import RunUsage

from tests.fakes import call_deps
from voice_agent.agent.carrie import build_agent
from voice_agent.agent.templates import template
from voice_agent.config import LlmProvider, Settings
from voice_agent.conversation.records import Message, Role, Source
from voice_agent.llm.providers import build_model, echo_model, llm_price
from voice_agent.llm.responder import (
    Responder,
    StreamedReply,
    dump_messages,
    to_model_history,
)

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
    reply = await Responder(None, timeout_s=1, max_tokens=10).reply(
        [], "Hi", call_deps()
    )

    assert reply.text == template("not_configured", "en")
    assert reply.source == "template"


def message(
    role: Role,
    source: Source,
    text: str,
    interrupted: bool = False,
    heard_text: str | None = None,
    model_messages: list[dict[str, Any]] | None = None,
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
        model_messages=model_messages,
    )


def test_history_leaves_out_the_greeting() -> None:
    history, note = to_model_history(
        [
            message("assistant", "template", "Hello, how can I help?"),
            message("user", "voice", "Hi"),
            message("assistant", "llm", "Hello!"),
            message("user", "keypad", "123"),
            # Fixed texts after the greeting (safety guidance) are kept
            message("assistant", "template", "Please move away from the vehicle."),
        ]
    )

    assert [type(m) for m in history] == [
        ModelRequest,
        ModelResponse,
        ModelRequest,
        ModelResponse,
    ]
    assert note is None


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
    history, note = to_model_history(
        [
            message("user", "voice", "Tell me a story"),
            message(
                "assistant",
                "llm",
                "Once upon a time. There was a king.",
                interrupted=True,
                heard_text="Once upon a time.",
            ),
        ]
    )

    assert prompts(history) == [["Tell me a story"]]
    assert note == "(You were interrupted. The caller heard only: 'Once upon a time.')"


def tool_turn(text_before: str = "One moment.") -> list[dict[str, Any]]:
    """A turn's stored messages: text, a tool call, its result, the answer."""
    stored = dump_messages(
        [
            ModelResponse(
                parts=[
                    TextPart(text_before),
                    ToolCallPart("lookup_order", {"order_number": "1"}, "call-1"),
                ]
            ),
            ModelRequest(
                parts=[ToolReturnPart("lookup_order", {"status": "ok"}, "call-1")]
            ),
            ModelResponse(parts=[TextPart("It's confirmed.")]),
        ]
    )
    assert stored is not None
    return stored


def test_tool_calls_are_replayed_with_the_text_the_caller_heard() -> None:
    history, _ = to_model_history(
        [
            message("user", "voice", "When is my car coming?"),
            message(
                "assistant",
                "llm",
                "One moment. It's confirmed.",
                model_messages=tool_turn(),
            ),
        ]
    )

    request, call, result, answer = history
    assert isinstance(request, ModelRequest)
    assert isinstance(call, ModelResponse)
    assert [type(p) for p in call.parts] == [ToolCallPart]
    assert isinstance(result, ModelRequest)
    assert [type(p) for p in result.parts] == [ToolReturnPart]
    assert isinstance(answer, ModelResponse)
    assert answer.parts == [TextPart("One moment. It's confirmed.")]


def test_a_tool_call_without_its_result_is_dropped() -> None:
    # The turn was cancelled while the tool ran
    stored = dump_messages(
        [
            ModelResponse(
                parts=[TextPart("One moment."), ToolCallPart("lookup_order", {}, "c-1")]
            ),
        ]
    )

    assert stored is None


async def collect(responder: Responder) -> tuple[list[str], StreamedReply]:
    deltas: list[str] = []

    async def on_text(delta: str) -> None:
        deltas.append(delta)

    reply = await responder.stream([], "Hi there", call_deps(), on_text)
    return deltas, reply


def agent(model: Model) -> Responder:
    return Responder(build_agent(model), timeout_s=5, max_tokens=100)


async def test_a_streamed_reply_arrives_piece_by_piece() -> None:
    deltas, reply = await collect(agent(echo_model()))

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

    _, reply = await collect(agent(FunctionModel(stream_function=breaking)))

    assert (reply.text, reply.failed) == ("Well,", True)


async def test_an_unconfigured_model_streams_a_fixed_reply() -> None:
    deltas, reply = await collect(Responder(None, timeout_s=1, max_tokens=10))

    assert deltas == [template("not_configured", "en")]
    assert reply.source == "template"


async def test_a_run_is_metered_with_its_price() -> None:
    responder = Responder(
        build_agent(echo_model()),
        timeout_s=5,
        max_tokens=100,
        name="echo",
        price=lambda usage: usage.output_tokens * 0.001,
    )

    async def ignore(delta: str) -> None:
        pass

    reply = await responder.stream([], "Hi", call_deps(), ignore)

    metered = reply.metered
    assert metered is not None
    assert (metered.service, metered.model) == ("llm", "echo")
    assert metered.output_tokens > 0
    assert metered.cost_usd == pytest.approx(metered.output_tokens * 0.001)
    assert metered.duration_ms >= 0


async def test_echo_costs_nothing() -> None:
    price = await llm_price(settings("echo"))

    assert price is not None
    assert price(RunUsage(input_tokens=10, output_tokens=5)) == 0
