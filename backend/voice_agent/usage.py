"""What the model calls of a turn consumed: time, tokens, audio and cost."""

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from genai_prices import Usage as PriceUsage
from genai_prices import calc_price
from pydantic import BaseModel, ConfigDict, field_validator

logger = logging.getLogger(__name__)

Service = Literal["stt", "llm", "tts"]

# Models billed by audio duration, in USD per minute; genai-prices lacks them
PRICE_PER_MINUTE = {"gpt-live-transcribe": 0.017, "gpt-realtime-whisper": 0.017}


class Usage(BaseModel):
    """One or more calls of one model for one service."""

    model_config = ConfigDict(frozen=True)

    service: Service
    model: str
    calls: int = 1
    input_tokens: int = 0
    output_tokens: int = 0
    # Audio the model heard or spoke
    audio_in_s: float = 0
    audio_out_s: float = 0
    # Wall time of the calls
    duration_ms: int = 0
    # None when the model has no known price; local models cost nothing
    cost_usd: float | None = 0

    @field_validator("cost_usd")
    @classmethod
    def _rounded(cls, cost: float | None) -> float | None:
        # Sums of prices carry float noise (0.0025500000000000006)
        return None if cost is None else round(cost, 8)

    def timed(self, duration_ms: int) -> "Usage":
        return self.model_copy(update={"duration_ms": duration_ms})


def combine(usages: Iterable[Usage | None]) -> list[Usage]:
    """One entry per service and model, e.g. for all spoken sentences.

    A combined cost is None if any of its calls has no known price.
    """
    totals: dict[tuple[str, str], Usage] = {}
    for usage in usages:
        if usage is None:
            continue
        key = (usage.service, usage.model)
        total = totals.get(key)
        totals[key] = (
            usage
            if total is None
            else Usage(
                service=usage.service,
                model=usage.model,
                calls=total.calls + usage.calls,
                input_tokens=total.input_tokens + usage.input_tokens,
                output_tokens=total.output_tokens + usage.output_tokens,
                audio_in_s=round(total.audio_in_s + usage.audio_in_s, 3),
                audio_out_s=round(total.audio_out_s + usage.audio_out_s, 3),
                duration_ms=total.duration_ms + usage.duration_ms,
                cost_usd=None
                if total.cost_usd is None or usage.cost_usd is None
                else total.cost_usd + usage.cost_usd,
            )
        )
    return list(totals.values())


def listed_cost(
    model: str,
    provider: str,
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cached_tokens: int = 0,
    input_audio_tokens: int = 0,
    output_audio_tokens: int = 0,
) -> float | None:
    """The price from genai-prices in USD, or None if it lists none."""
    try:
        price = calc_price(
            PriceUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_read_tokens=cached_tokens,
                input_audio_tokens=input_audio_tokens,
                output_audio_tokens=output_audio_tokens,
            ),
            model,
            provider_id=provider,
        )
    except LookupError:
        logger.warning("No price known for %s (%s)", model, provider)
        return None
    # The list carries some new models before their prices
    if not price.total_price and (input_tokens or output_tokens):
        return None
    return float(price.total_price)


@dataclass(frozen=True)
class TokenPrice:
    """USD per token."""

    input: float
    cached_input: float
    output: float

    def cost(self, input_tokens: int, cached_tokens: int, output_tokens: int) -> float:
        return (
            (input_tokens - cached_tokens) * self.input
            + cached_tokens * self.cached_input
            + output_tokens * self.output
        )
