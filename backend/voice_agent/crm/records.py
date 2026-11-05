"""What the customer care system returns: immutable records, no ORM objects."""

from datetime import date, datetime
from typing import Any, Literal, get_args
from uuid import UUID

from pydantic import BaseModel, ConfigDict, computed_field

Topic = Literal["delivery", "charging", "connected_services", "warranty"]
TicketStatus = Literal[
    "open", "in_progress", "waiting_on_customer", "resolved", "closed"
]
Priority = Literal["normal", "high", "urgent", "safety"]
Route = Literal[
    "delivery",
    "technical_support",
    "warranty_service",
    "account_security",
    "roadside_assistance",
    "language_support",
    "general",
]
HandoverStatus = Literal["transferred", "unavailable"]
NoteAuthor = Literal["carrie", "care_agent", "system"]
VerificationStatus = Literal["unverified", "order_verified", "ticket_verified"]

TOPICS: tuple[str, ...] = get_args(Topic)
TICKET_STATUSES: tuple[str, ...] = get_args(TicketStatus)
OPEN_STATUSES: tuple[TicketStatus, ...] = ("open", "in_progress", "waiting_on_customer")
PRIORITIES: tuple[str, ...] = get_args(Priority)
ROUTES: tuple[str, ...] = get_args(Route)
HANDOVER_STATUSES: tuple[str, ...] = get_args(HandoverStatus)
NOTE_AUTHORS: tuple[str, ...] = get_args(NoteAuthor)

TICKET_PREFIX = "CC-"


def ticket_reference(number: int) -> str:
    return f"{TICKET_PREFIX}{number}"


class Record(BaseModel):
    model_config = ConfigDict(frozen=True)


class Customer(Record):
    id: int
    first_name: str
    last_name: str
    postal_code: str
    city: str
    mobile_phone: str
    email: str
    preferred_language: str


class Order(Record):
    order_number: str
    customer_id: int
    model: str
    status: str
    ordered_on: date
    confirmed_delivery_date: date | None
    estimate_from: date | None
    estimate_to: date | None
    previous_estimate_from: date | None
    previous_estimate_to: date | None
    status_reason: str | None
    dealer: str
    status_updated_at: datetime


class Note(Record):
    author: NoteAuthor
    body: str
    created_at: datetime


class Ticket(Record):
    number: int
    topic: Topic
    issue_type: str
    status: TicketStatus
    priority: Priority
    summary: str
    details: dict[str, Any]
    customer_id: int | None
    order_number: str | None
    mobile_phone: str | None
    verification_status: VerificationStatus
    language: str
    conversation_id: UUID | None
    created_at: datetime
    updated_at: datetime

    @computed_field
    @property
    def reference(self) -> str:
        return ticket_reference(self.number)


class TicketDetail(Ticket):
    """A ticket with its notes and customer, for the care desk."""

    customer_name: str | None
    # The customer's postal code, for the care team
    postal_code: str | None
    vehicle_model: str | None
    notes: list[Note]


class NewTicket(Record):
    topic: Topic
    issue_type: str
    priority: Priority
    summary: str
    details: dict[str, Any]
    order_number: str | None
    mobile_phone: str | None
    verification_status: VerificationStatus
    language: str
    conversation_id: UUID | None


class NewHandover(Record):
    conversation_id: UUID | None
    ticket_number: int | None
    route: Route
    priority: Priority
    language: str
    reason: str
    summary: str
    details: dict[str, Any]
    status: HandoverStatus


class Handover(NewHandover):
    id: int
    created_at: datetime
