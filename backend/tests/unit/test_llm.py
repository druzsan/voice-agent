from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic_ai.messages import ModelRequest, ModelResponse
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel
from pydantic_ai.models.openrouter import OpenRouterModel

from voice_agent.config import LlmProvider, Settings
from voice_agent.conversation.records import Message, Role, Source
from voice_agent.llm.prompts import LLM_NOT_CONFIGURED
from voice_agent.llm.providers import build_model
from voice_agent.llm.responder import Responder, to_model_history

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
    assert model.base_url == "https://router.requesty.ai/v1/"


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


def message(role: Role, source: Source, text: str) -> Message:
    return Message(
        id=1,
        conversation_id=uuid4(),
        created_at=datetime.now(UTC),
        role=role,
        source=source,
        text=text,
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
