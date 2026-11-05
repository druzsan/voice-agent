import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx
from pydantic import SecretStr
from pydantic_ai.exceptions import UserError
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)
from pydantic_ai.models import Model
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel
from pydantic_ai.models.openrouter import OpenRouterModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.providers.openai_compatible import OpenAICompatibleProvider
from pydantic_ai.providers.openrouter import OpenRouterProvider

from voice_agent.config import Settings
from voice_agent.llm.responder import LlmPrice
from voice_agent.usage import TokenPrice, listed_cost

logger = logging.getLogger(__name__)


def _last_user_text(messages: list[ModelMessage]) -> str:
    for message in reversed(messages):
        if isinstance(message, ModelRequest):
            for part in reversed(message.parts):
                if isinstance(part, UserPromptPart) and isinstance(part.content, str):
                    return part.content
    return ""


def _echo_text(messages: list[ModelMessage]) -> str:
    return f"You said: {_last_user_text(messages)}"


def _echo(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    return ModelResponse(parts=[TextPart(_echo_text(messages))])


async def _echo_stream(
    messages: list[ModelMessage], info: AgentInfo
) -> AsyncIterator[str]:
    # Word by word, like a provider streams its tokens
    for word in _echo_text(messages).split(" "):
        yield f"{word} "


def echo_model() -> Model:
    """Repeats the caller: the full reply path without a provider or key."""
    return FunctionModel(_echo, stream_function=_echo_stream, model_name="echo")


def _key(name: str, key: SecretStr | None) -> str | None:
    if key is None:
        logger.warning("%s is not set; the language model is not configured", name)
        return None
    return key.get_secret_value()


def build_model(settings: Settings) -> Model | None:
    """The configured model, or None when it can't be set up.

    A missing model ID or key, or a model ID the provider rejects, is logged
    instead of stopping the app; the status endpoint then reports the model
    as not configured.
    """
    if settings.llm_provider == "echo":
        return echo_model()
    if settings.llm_model is None:
        logger.warning(
            "VOICE_AGENT_LLM_MODEL is not set; the language model is not configured"
        )
        return None
    try:
        return _provider_model(settings, settings.llm_model)
    except UserError as error:
        logger.error("The language model is not configured: %s", error)
        return None


def _provider_model(settings: Settings, model: str) -> Model | None:
    match settings.llm_provider:
        case "openai":
            if (key := _key("OPENAI_API_KEY", settings.openai_api_key)) is None:
                return None
            # The Responses API is OpenAI's recommended one
            return OpenAIResponsesModel(
                model,
                provider=OpenAIProvider(api_key=key, base_url=settings.openai_base_url),
            )
        case "requesty":
            if (key := _key("REQUESTY_API_KEY", settings.requesty_api_key)) is None:
                return None
            # Requesty is an OpenAI-compatible router (Chat Completions)
            return OpenAIChatModel(
                model,
                provider=OpenAICompatibleProvider(
                    "requesty", base_url=settings.requesty_base_url, api_key=key
                ),
            )
        case "openrouter":
            if (key := _key("OPENROUTER_API_KEY", settings.openrouter_api_key)) is None:
                return None
            return OpenRouterModel(model, provider=OpenRouterProvider(api_key=key))
        case "echo":
            return echo_model()


def model_name(settings: Settings) -> str:
    """The model as stored with its usage, with its provider."""
    if settings.llm_provider == "echo" or settings.llm_model is None:
        return settings.llm_provider
    return f"{settings.llm_provider}/{settings.llm_model}"


async def requesty_price(model: str, api_key: str, base_url: str) -> TokenPrice | None:
    """The model's price from Requesty's model list, including its margin.

    Requesty's model IDs (e.g. azure/gpt-6.1-sol@germanywestcentral) aren't in
    the genai-prices list.
    """
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{base_url.rstrip('/')}/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            response.raise_for_status()
        entries: list[dict[str, Any]] = response.json().get("data", [])
    except (httpx.HTTPError, ValueError):
        logger.warning("Couldn't load Requesty's prices; LLM costs stay unknown")
        return None
    for entry in entries:
        if entry.get("id") == model:
            return TokenPrice(
                input=float(entry["input_price"]),
                cached_input=float(entry.get("cached_price") or entry["input_price"]),
                output=float(entry["output_price"]),
            )
    logger.warning("Requesty lists no price for %s; LLM costs stay unknown", model)
    return None


async def llm_price(settings: Settings) -> LlmPrice | None:
    """How a run of the configured model is priced; None when unknown."""
    model = settings.llm_model
    match settings.llm_provider:
        case "echo":
            return lambda usage: 0.0
        case "requesty":
            key = settings.requesty_api_key
            if model is None or key is None:
                return None
            price = await requesty_price(
                model, key.get_secret_value(), settings.requesty_base_url
            )
            if price is None:
                return None
            return lambda usage: price.cost(
                usage.input_tokens, usage.cache_read_tokens, usage.output_tokens
            )
        case "openai" | "openrouter":
            if model is None:
                return None
            provider = settings.llm_provider
            return lambda usage: listed_cost(
                model,
                provider,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cached_tokens=usage.cache_read_tokens,
            )
