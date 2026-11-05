import logging
import time
from collections.abc import Awaitable, Callable, Sequence
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
from pydantic_ai.usage import RunUsage

from voice_agent.conversation.records import Message
from voice_agent.llm.prompts import (
    LLM_FAILED,
    LLM_NOT_CONFIGURED,
    SYSTEM_PROMPT,
    interruption_note,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Reply:
    text: str
    # "template" when the model wasn't asked or failed
    source: Literal["llm", "template"]
    usage: dict[str, int] | None = None


@dataclass(frozen=True)
class StreamedReply:
    text: str
    # "template" when the model wasn't asked
    source: Literal["llm", "template"]
    usage: dict[str, int] | None = None
    # The model failed partway; `text` holds what it said before
    failed: bool = False
    # From the request to the first text and to the end of the answer
    first_token_ms: int | None = None
    total_ms: int | None = None


def _usage(usage: RunUsage) -> dict[str, int]:
    return {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "requests": usage.requests,
    }


def to_model_history(
    messages: Sequence[Message], text: str | None = None
) -> list[ModelMessage]:
    """Earlier caller and model messages, as the model sees them.

    Fixed texts (greeting, fallbacks) are left out: the model didn't write
    them, and some providers reject a history that starts with an assistant
    turn. The system prompt mentions the greeting instead.

    A reply the caller interrupted stays as the model wrote it, and the
    caller's next message comes with a note on what the caller heard of it.
    With `text`, the history ends with that new caller message.
    """
    history: list[ModelMessage] = []
    note: str | None = None

    def ask(prompt: str) -> None:
        nonlocal note
        parts = [UserPromptPart(note)] if note else []
        history.append(ModelRequest(parts=[*parts, UserPromptPart(prompt)]))
        note = None

    for message in messages:
        if message.role == "user":
            ask(message.text)
        elif message.source == "llm" and history:
            history.append(ModelResponse(parts=[TextPart(message.text)]))
            if message.interrupted:
                note = interruption_note(message.heard_text)
    if text is not None:
        ask(text)
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
                    None,
                    message_history=to_model_history(history, text),
                    model_settings=self._settings,
                )
        except Exception:
            logger.exception("The language model failed to answer")
            return Reply(LLM_FAILED, "template")
        answer = result.output.strip()
        if not answer:
            logger.warning("The language model returned an empty answer")
            return Reply(LLM_FAILED, "template")
        return Reply(answer, "llm", _usage(result.usage))

    async def stream(
        self,
        history: Sequence[Message],
        text: str,
        on_text: Callable[[str], Awaitable[None]],
    ) -> StreamedReply:
        """Answer piece by piece: `on_text` gets the text as it arrives.

        A failure doesn't raise; the result says how far the model got, so
        the caller can keep the part that was already spoken.
        """
        if self._agent is None:
            await on_text(LLM_NOT_CONFIGURED)
            return StreamedReply(LLM_NOT_CONFIGURED, "template")
        started = time.perf_counter()
        first_token_ms: int | None = None
        pieces: list[str] = []
        try:
            with anyio.fail_after(self._timeout_s):
                async with self._agent.run_stream(
                    None,
                    message_history=to_model_history(history, text),
                    model_settings=self._settings,
                ) as result:
                    async for delta in result.stream_text(delta=True, debounce_by=None):
                        if not delta:
                            continue
                        if first_token_ms is None:
                            first_token_ms = _ms_since(started)
                        pieces.append(delta)
                        await on_text(delta)
                    usage = _usage(result.usage)
        except Exception:
            logger.exception("The language model failed while answering")
            return StreamedReply(
                "".join(pieces).strip(),
                "llm",
                failed=True,
                first_token_ms=first_token_ms,
                total_ms=_ms_since(started),
            )
        answer = "".join(pieces).strip()
        if not answer:
            logger.warning("The language model returned an empty answer")
        return StreamedReply(
            answer,
            "llm",
            usage,
            failed=not answer,
            first_token_ms=first_token_ms,
            total_ms=_ms_since(started),
        )


def _ms_since(start: float) -> int:
    return round((time.perf_counter() - start) * 1000)
