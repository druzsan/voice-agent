import logging

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

logger = logging.getLogger(__name__)


def _last_user_text(messages: list[ModelMessage]) -> str:
    for message in reversed(messages):
        if isinstance(message, ModelRequest):
            for part in reversed(message.parts):
                if isinstance(part, UserPromptPart) and isinstance(part.content, str):
                    return part.content
    return ""


def _echo(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    return ModelResponse(parts=[TextPart(f"You said: {_last_user_text(messages)}")])


def echo_model() -> Model:
    """Repeats the caller: the full reply path without a provider or key."""
    return FunctionModel(_echo, model_name="echo")


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
            return OpenAIResponsesModel(model, provider=OpenAIProvider(api_key=key))
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
