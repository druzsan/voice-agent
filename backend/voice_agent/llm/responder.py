import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal

import anyio
from pydantic_ai import Agent
from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    PartDeltaEvent,
    PartStartEvent,
    TextPart,
    TextPartDelta,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.models import Model
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import RunUsage

from voice_agent.agent.deps import CallDeps
from voice_agent.agent.templates import template
from voice_agent.conversation.records import Message
from voice_agent.llm.prompts import interruption_note
from voice_agent.usage import Usage

logger = logging.getLogger(__name__)

# The cost of a model run in USD, None when unknown
LlmPrice = Callable[[RunUsage], float | None]


@dataclass(frozen=True)
class Reply:
    text: str
    # "template" when the model wasn't asked or failed
    source: Literal["llm", "template"]
    usage: dict[str, int] | None = None
    # Tokens, time and cost of the model run; None when it didn't run
    metered: Usage | None = None


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
    # Tokens, time and cost of the model run; None when it didn't run, or
    # failed before it reported usage
    metered: Usage | None = None


@dataclass
class TurnTrace:
    """What a model run did, kept even when it's cancelled partway."""

    # The run's messages after the caller's prompt (PydanticAI's JSON)
    model_messages: list[dict[str, Any]] | None = None


def _usage(usage: RunUsage) -> dict[str, int]:
    return {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "requests": usage.requests,
    }


def _complete(messages: list[ModelMessage]) -> list[ModelMessage]:
    """The messages up to the last tool call that got its result.

    A run cancelled while a tool ran leaves a call without a result, which
    providers reject in a history.
    """
    kept: list[ModelMessage] = []
    pending: set[str] = set()
    complete_at = 0
    for message in messages:
        kept.append(message)
        if isinstance(message, ModelResponse):
            pending |= {
                part.tool_call_id
                for part in message.parts
                if isinstance(part, ToolCallPart)
            }
        else:
            pending -= {
                answered for part in message.parts if (answered := _answers(part))
            }
        if not pending:
            complete_at = len(kept)
    return kept[:complete_at]


def _answers(part: object) -> str | None:
    """The tool call a request part answers (a result or a retry), if any."""
    if isinstance(part, UserPromptPart):
        return None
    call_id = getattr(part, "tool_call_id", None)
    return call_id if isinstance(call_id, str) else None


def dump_messages(messages: list[ModelMessage]) -> list[dict[str, Any]] | None:
    complete = _complete(messages)
    if not complete:
        return None
    return ModelMessagesTypeAdapter.dump_python(complete, mode="json")


def _tool_exchanges(stored: list[dict[str, Any]]) -> list[ModelMessage]:
    """A turn's tool calls and results, without its text.

    The text the caller actually heard is replayed from the message, after
    the reply check, instead of what the model first wrote.
    """
    exchanges: list[ModelMessage] = []
    for message in ModelMessagesTypeAdapter.validate_python(stored):
        if isinstance(message, ModelResponse):
            calls = [p for p in message.parts if isinstance(p, ToolCallPart)]
            if calls:
                exchanges.append(ModelResponse(parts=calls))
        else:
            results = [p for p in message.parts if _answers(p)]
            if results:
                exchanges.append(ModelRequest(parts=results))
    return exchanges


def to_model_history(
    messages: Sequence[Message],
) -> tuple[list[ModelMessage], str | None]:
    """Earlier caller and assistant messages as the model sees them.

    Returns the history and a note for the next caller message, when the
    caller interrupted the last reply. The greeting is left out: some
    providers reject a history that starts with an assistant turn, and the
    instructions mention it. A turn's tool calls and results are replayed,
    so the model knows what it looked up earlier.
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
            continue
        if not history:
            continue
        if message.model_messages:
            history.extend(_tool_exchanges(message.model_messages))
        if message.text:
            history.append(ModelResponse(parts=[TextPart(message.text)]))
        if message.interrupted:
            note = interruption_note(message.heard_text)
    return history, note


class Responder:
    """Carrie's answers from the configured language model, with her tools."""

    def __init__(
        self,
        agent: Agent[CallDeps, str] | None,
        timeout_s: float,
        max_tokens: int,
        *,
        name: str | None = None,
        price: LlmPrice | None = None,
    ) -> None:
        self._agent = agent
        self._timeout_s = timeout_s
        self._settings = ModelSettings(max_tokens=max_tokens)
        model = agent.model if agent is not None else None
        self._name = name or (model.model_name if isinstance(model, Model) else "none")
        self._price = price

    def _metered(self, usage: RunUsage, duration_ms: int) -> Usage:
        try:
            cost = self._price(usage) if self._price else None
        except Exception:
            logger.exception("Couldn't price a model run")
            cost = None
        return Usage(
            service="llm",
            model=self._name,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            duration_ms=duration_ms,
            cost_usd=cost,
        )

    @property
    def configured(self) -> bool:
        return self._agent is not None

    async def reply(
        self,
        history: Sequence[Message],
        text: str,
        deps: CallDeps,
        trace: TurnTrace | None = None,
    ) -> Reply:
        """The whole answer at once (push-to-talk)."""
        if self._agent is None:
            return Reply(template("not_configured", deps.state.language), "template")
        trace = trace or TurnTrace()
        model_history, note = to_model_history(history)
        started = time.perf_counter()
        try:
            with anyio.fail_after(self._timeout_s):
                result = await self._agent.run(
                    f"{note}\n{text}" if note else text,
                    message_history=model_history,
                    deps=deps,
                    model_settings=self._settings,
                )
        except Exception:
            logger.exception("The language model failed to answer")
            return Reply(template("llm_failed", deps.state.language), "template")
        trace.model_messages = dump_messages(result.new_messages()[1:])
        answer = result.output.strip()
        if not answer:
            logger.warning("The language model returned an empty answer")
            return Reply(template("llm_failed", deps.state.language), "template")
        usage = result.usage
        return Reply(
            answer, "llm", _usage(usage), self._metered(usage, _ms_since(started))
        )

    async def stream(
        self,
        history: Sequence[Message],
        text: str,
        deps: CallDeps,
        on_text: Callable[[str], Awaitable[None]],
        *,
        trace: TurnTrace | None = None,
    ) -> StreamedReply:
        """Answer piece by piece: `on_text` gets the text as it arrives.

        Tools run between the pieces. Each model response ends with a space,
        so a sentence said before a tool call is complete while the tool runs.
        A failure doesn't raise; the result says how far the model got. The
        run's messages land in `trace`, also when the run is cancelled.
        """
        if self._agent is None:
            fallback = template("not_configured", deps.state.language)
            await on_text(fallback)
            return StreamedReply(fallback, "template")
        trace = trace or TurnTrace()
        model_history, note = to_model_history(history)
        prompt = f"{note}\n{text}" if note else text
        started = time.perf_counter()
        first_token_ms: int | None = None
        pieces: list[str] = []

        async def emit(piece: str) -> None:
            nonlocal first_token_ms
            if first_token_ms is None:
                first_token_ms = _ms_since(started)
            pieces.append(piece)
            await on_text(piece)

        run_usage: RunUsage | None = None
        try:
            with anyio.fail_after(self._timeout_s):
                async with self._agent.iter(
                    prompt,
                    message_history=model_history,
                    deps=deps,
                    model_settings=self._settings,
                ) as run:
                    try:
                        async for node in run:
                            if not Agent.is_model_request_node(node):
                                continue
                            async with node.stream(run.ctx) as events:
                                async for event in events:
                                    piece = _text_of(event)
                                    if piece:
                                        await emit(piece)
                            if pieces and not pieces[-1][-1].isspace():
                                await emit(" ")
                    finally:
                        # The caller's prompt is stored as their message
                        trace.model_messages = dump_messages(run.new_messages()[1:])
                        run_usage = run.usage
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
        total_ms = _ms_since(started)
        assert run_usage is not None
        return StreamedReply(
            answer,
            "llm",
            _usage(run_usage),
            failed=not answer,
            first_token_ms=first_token_ms,
            total_ms=total_ms,
            metered=self._metered(run_usage, total_ms),
        )


def _text_of(event: object) -> str:
    if isinstance(event, PartStartEvent) and isinstance(event.part, TextPart):
        return event.part.content
    if isinstance(event, PartDeltaEvent) and isinstance(event.delta, TextPartDelta):
        return event.delta.content_delta
    return ""


def _ms_since(start: float) -> int:
    return round((time.perf_counter() - start) * 1000)
