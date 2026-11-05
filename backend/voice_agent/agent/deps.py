"""What Carrie's tools work with during one call."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from voice_agent.agent.state import CallState
from voice_agent.crm.port import Crm


@dataclass(frozen=True)
class CarrieSettings:
    supported_languages: tuple[str, ...]
    # Routes that report "no colleague available"
    unavailable_routes: frozenset[str]
    timezone: ZoneInfo


@dataclass(frozen=True)
class ToolEvent:
    """A tool call as the transcript shows it."""

    name: str
    status: Literal["ok", "refused", "failed"]
    # Short, for people: "Order 456789 verified"
    label: str
    # Shown to the caller's screen as is, so nothing secret in here
    data: dict[str, Any] = field(default_factory=dict[str, Any])

    def as_record(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "label": self.label,
            "data": self.data,
        }


@dataclass
class CallDeps:
    state: CallState
    crm: Crm
    settings: CarrieSettings
    conversation_id: UUID | None
    # Called as each tool finishes, e.g. to show it in the call
    on_event: Callable[[ToolEvent], Awaitable[None]] | None = None
    events: list[ToolEvent] = field(default_factory=list[ToolEvent])

    def now(self) -> datetime:
        return datetime.now(self.settings.timezone)

    async def record(self, event: ToolEvent) -> None:
        self.events.append(event)
        if self.on_event is not None:
            await self.on_event(event)
