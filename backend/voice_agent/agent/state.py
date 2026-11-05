"""What Carrie knows for certain during a call, restated to the model every turn.

Only facts the tools established live here (verified orders, tickets,
transfers, identification attempts), plus the conversation language and
whether danger was reported. Topics, symptoms and what the caller tried stay
in the conversation itself, where the model reads them.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from voice_agent.agent.language import language_name
from voice_agent.crm.records import Route, Topic

# Failed identification attempts before Carrie stops trying and offers a person
MAX_FAILED_LOOKUPS = 2


class VerifiedOrder(BaseModel):
    order_number: str
    customer_name: str
    # What the lookup returned, as the model was told
    facts: str


class CallTicket(BaseModel):
    reference: str
    topic: Topic
    status: str
    # found: identified with find_open_tickets; created in this call
    origin: Literal["found", "created"]
    summary: str
    notes_added: int = 0


class CallHandover(BaseModel):
    route: Route
    status: Literal["transferred", "unavailable"]


class CallState(BaseModel):
    language: str = "en"
    # The caller's number as the phone line reports it
    caller_phone: str | None = None
    verified_orders: list[VerifiedOrder] = Field(default_factory=list[VerifiedOrder])
    failed_order_lookups: int = 0
    failed_ticket_lookups: int = 0
    tickets: list[CallTicket] = Field(default_factory=list[CallTicket])
    handovers: list[CallHandover] = Field(default_factory=list[CallHandover])
    emergency: bool = False
    # Set by a successful transfer: the call goes on hold after the reply
    hold_requested: bool = False

    def ticket(self, reference: str) -> CallTicket | None:
        return next((t for t in self.tickets if t.reference == reference), None)

    @property
    def transferred(self) -> bool:
        return any(h.status == "transferred" for h in self.handovers)

    @property
    def tickets_changed(self) -> bool:
        """A ticket was created or updated in this call."""
        return any(t.origin == "created" or t.notes_added for t in self.tickets)


def describe(state: CallState, now: datetime, supported: tuple[str, ...]) -> str:
    """The state block appended to the instructions before every model call."""
    lines = [
        "# Current call",
        f"Now: {now:%A, %-d %B %Y, %H:%M} ({now.tzname()}).",
        (
            f"Conversation language: {language_name(state.language)}. Supported "
            f"languages: {', '.join(language_name(code) for code in supported)}."
        ),
    ]
    if state.caller_phone:
        lines.append(
            f"Caller's number from the phone line: {state.caller_phone} "
            "(used for tickets unless the caller gives another one; not proof of identity)."
        )
    else:
        lines.append("The phone line shows no caller number.")
    for order in state.verified_orders:
        lines.append(
            f"Verified order {order.order_number} ({order.customer_name}): {order.facts}"
        )
    if state.failed_order_lookups:
        lines.append(
            f"Failed order identifications: {state.failed_order_lookups} of "
            f"{MAX_FAILED_LOOKUPS}."
        )
    if state.failed_ticket_lookups:
        lines.append(
            f"Failed ticket identifications: {state.failed_ticket_lookups} of "
            f"{MAX_FAILED_LOOKUPS}."
        )
    for ticket in state.tickets:
        notes = f", {ticket.notes_added} note(s) added" if ticket.notes_added else ""
        lines.append(
            f"Ticket {ticket.reference} ({ticket.origin} in this call, {ticket.topic}, "
            f"{ticket.status}{notes}): {ticket.summary}"
        )
    if not state.tickets:
        lines.append("No ticket identified or created in this call.")
    for handover in state.handovers:
        route = handover.route.replace("_", " ")
        if handover.status == "transferred" and state.hold_requested:
            lines.append(
                f"Transfer to {route} confirmed just now: the caller goes on hold "
                "after your reply until a colleague picks up."
            )
        elif handover.status == "transferred":
            lines.append(
                f"Transferred to {route} earlier; the caller was on hold and is "
                "back with you. No colleague has taken over yet."
            )
        else:
            lines.append(
                f"Transfer to {handover.route.replace('_', ' ')} was unavailable."
            )
    if state.emergency:
        lines.append(
            "DANGER WAS REPORTED in this call and safety instructions were given. "
            "No troubleshooting or routine questions while it may persist."
        )
    return "\n".join(lines)
