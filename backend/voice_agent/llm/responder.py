import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import anyio
from pydantic_ai import Agent
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)
from pydantic_ai.models import Model
from pydantic_ai.settings import ModelSettings

from voice_agent.conversation.records import Message
from voice_agent.llm.prompts import LLM_FAILED, LLM_NOT_CONFIGURED, SYSTEM_PROMPT

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Reply:
    text: str
    # "template" when the model wasn't asked or failed
    source: Literal["llm", "template"]
    usage: dict[str, int] | None = None


def to_model_history(messages: Sequence[Message]) -> list[ModelMessage]:
    """Earlier caller and model messages, as the model sees them.

    Fixed texts (greeting, fallbacks) are left out: the model didn't write
    them, and some providers reject a history that starts with an assistant
    turn. The system prompt mentions the greeting instead.
    """
    history: list[ModelMessage] = []
    for message in messages:
        if message.role == "user":
            history.append(ModelRequest(parts=[UserPromptPart(message.text)]))
        elif message.source == "llm" and history:
            history.append(ModelResponse(parts=[TextPart(message.text)]))
    return history


class Responder:
    """Plain answers from the configured language model, without tools."""

    def __init__(self, model: Model | None, timeout_s: float, max_tokens: int) -> None:
        self._agent = (
            Agent(model, instructions=SYSTEM_PROMPT, output_type=str) if model else None
        )
        self._timeout_s = timeout_s
        self._settings = ModelSettings(max_tokens=max_tokens)

    @property
    def configured(self) -> bool:
        return self._agent is not None

    async def reply(self, history: Sequence[Message], text: str) -> Reply:
        if self._agent is None:
            return Reply(LLM_NOT_CONFIGURED, "template")
        try:
            with anyio.fail_after(self._timeout_s):
                result = await self._agent.run(
                    text,
                    message_history=to_model_history(history),
                    model_settings=self._settings,
                )
        except Exception:
            logger.exception("The language model failed to answer")
            return Reply(LLM_FAILED, "template")
        answer = result.output.strip()
        if not answer:
            logger.warning("The language model returned an empty answer")
            return Reply(LLM_FAILED, "template")
        usage = result.usage
        return Reply(
            answer,
            "llm",
            {
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "requests": usage.requests,
            },
        )
