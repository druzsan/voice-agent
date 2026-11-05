from typing import Protocol
from uuid import UUID

from voice_agent.crm.records import (
    Customer,
    Handover,
    NewHandover,
    NewTicket,
    NoteAuthor,
    Order,
    Priority,
    Ticket,
    TicketDetail,
    TicketStatus,
    Topic,
)


class Crm(Protocol):
    """The customer care system: customers, orders, tickets and handovers.

    The app uses its own PostgreSQL schema (voice_agent.crm.sql); a real
    system (Dynamics 365, Salesforce, ...) would be another implementation.
    It stores and finds records; who may see what is decided by the agent's
    tools, which apply the identification rules.
    """

    async def get_order(self, order_number: str) -> Order | None: ...

    async def get_customer(self, customer_id: int) -> Customer | None: ...

    async def search_tickets(
        self,
        *,
        number: int | None = None,
        mobile_phone: str | None = None,
        order_number: str | None = None,
        statuses: tuple[TicketStatus, ...] | None = None,
    ) -> list[TicketDetail]:
        """Tickets matching any of the given identifiers, newest first.

        `mobile_phone` matches the ticket's number and its customer's.
        """
        ...

    async def create_ticket(self, ticket: NewTicket) -> Ticket:
        """Links the ticket to the order's customer when the order exists."""
        ...

    async def add_note(
        self,
        number: int,
        author: NoteAuthor,
        body: str,
        conversation_id: UUID | None,
        priority: Priority | None = None,
    ) -> Ticket:
        """Adds a note; a ticket waiting on the customer becomes open again."""
        ...

    async def create_handover(self, handover: NewHandover) -> Handover: ...

    # --- The care desk ---------------------------------------------------------

    async def list_tickets(
        self,
        *,
        status: TicketStatus | None = None,
        topic: Topic | None = None,
        limit: int = 100,
    ) -> list[TicketDetail]: ...

    async def get_ticket(self, number: int) -> TicketDetail | None: ...

    async def list_handovers(self, limit: int = 100) -> list[Handover]: ...
