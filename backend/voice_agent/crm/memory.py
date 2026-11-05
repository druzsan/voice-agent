"""The customer care system in memory, with the same starting data.

For tests and the scenario evaluation: Carrie's tools run against it exactly
as against PostgreSQL, without a database.
"""

from datetime import UTC, date, datetime
from uuid import UUID

from voice_agent.crm.models import FIRST_TICKET_NUMBER
from voice_agent.crm.records import (
    Customer,
    Handover,
    NewHandover,
    NewTicket,
    Note,
    NoteAuthor,
    Order,
    Priority,
    Ticket,
    TicketDetail,
    TicketStatus,
    Topic,
)
from voice_agent.crm.seed_data import BERLIN, CASES, day, moment

_PRIORITY_RANK = {"normal": 0, "high": 1, "urgent": 2, "safety": 3}


class InMemoryCrm:
    def __init__(self) -> None:
        self.customers: dict[int, Customer] = {}
        self.orders: dict[str, Order] = {}
        self.tickets: dict[int, Ticket] = {}
        self.notes: dict[int, list[Note]] = {}
        # Ticket number -> vehicle model, for the desk view
        self.models: dict[int, str] = {}
        self.handovers: list[Handover] = []

    @classmethod
    def seeded(cls, today: date | None = None) -> "InMemoryCrm":
        """With the 20 starting cases, dated relative to `today`."""
        today = today or datetime.now(BERLIN).date()
        crm = cls()
        for index, case in enumerate(CASES, start=1):
            c = case.customer
            crm.customers[index] = Customer(
                id=index,
                first_name=c.first_name,
                last_name=c.last_name,
                postal_code=c.postal_code,
                city=c.city,
                mobile_phone=c.mobile_phone,
                email=c.email,
                preferred_language=c.preferred_language,
            )
            if (o := case.order) is not None:
                estimate, previous = o.estimate_in_days, o.previous_estimate_in_days
                crm.orders[o.order_number] = Order(
                    order_number=o.order_number,
                    customer_id=index,
                    model=o.model,
                    status=o.status,
                    ordered_on=day(today, -o.ordered_days_ago),
                    confirmed_delivery_date=(
                        day(today, o.confirmed_in_days)
                        if o.confirmed_in_days is not None
                        else None
                    ),
                    estimate_from=day(today, estimate[0]) if estimate else None,
                    estimate_to=day(today, estimate[1]) if estimate else None,
                    previous_estimate_from=day(today, previous[0])
                    if previous
                    else None,
                    previous_estimate_to=day(today, previous[1]) if previous else None,
                    status_reason=o.status_reason,
                    dealer=o.dealer,
                    status_updated_at=moment(today, o.status_updated_days_ago, hour=8),
                )
            t = case.ticket
            number = FIRST_TICKET_NUMBER + index - 1
            created = moment(today, t.created_days_ago)
            notes = [
                Note(
                    author=n.author,
                    body=n.body,
                    created_at=moment(today, n.days_ago, hour=15),
                )
                for n in t.notes
            ]
            crm.tickets[number] = Ticket(
                number=number,
                topic=t.topic,
                issue_type=t.issue_type,
                status=t.status,
                priority=t.priority,
                summary=t.summary,
                details=t.details,
                customer_id=index,
                order_number=case.order.order_number if case.order else None,
                mobile_phone=c.mobile_phone,
                verification_status="order_verified" if case.order else "unverified",
                language=c.preferred_language,
                conversation_id=None,
                created_at=created,
                updated_at=max([created, *(n.created_at for n in notes)]),
            )
            crm.notes[number] = notes
            model = (
                case.vehicle.model
                if case.vehicle
                else case.order.model
                if case.order
                else None
            )
            if model:
                crm.models[number] = model
        return crm

    async def get_order(self, order_number: str) -> Order | None:
        return self.orders.get(order_number)

    async def get_customer(self, customer_id: int) -> Customer | None:
        return self.customers.get(customer_id)

    def _detail(self, ticket: Ticket) -> TicketDetail:
        customer = (
            self.customers.get(ticket.customer_id) if ticket.customer_id else None
        )
        return TicketDetail(
            **ticket.model_dump(),
            customer_name=(
                f"{customer.first_name} {customer.last_name}" if customer else None
            ),
            postal_code=customer.postal_code if customer else None,
            vehicle_model=self.models.get(ticket.number),
            notes=list(self.notes.get(ticket.number, [])),
        )

    def _newest_first(self, tickets: list[Ticket]) -> list[TicketDetail]:
        tickets.sort(key=lambda t: (t.updated_at, t.number), reverse=True)
        return [self._detail(t) for t in tickets]

    async def search_tickets(
        self,
        *,
        number: int | None = None,
        mobile_phone: str | None = None,
        order_number: str | None = None,
        statuses: tuple[TicketStatus, ...] | None = None,
    ) -> list[TicketDetail]:
        def matches(ticket: Ticket) -> bool:
            customer = (
                self.customers.get(ticket.customer_id) if ticket.customer_id else None
            )
            return (
                (number is not None and ticket.number == number)
                or (order_number is not None and ticket.order_number == order_number)
                or (
                    mobile_phone is not None
                    and (
                        ticket.mobile_phone == mobile_phone
                        or (
                            customer is not None
                            and customer.mobile_phone == mobile_phone
                        )
                    )
                )
            )

        return self._newest_first(
            [
                t
                for t in self.tickets.values()
                if matches(t) and (statuses is None or t.status in statuses)
            ]
        )

    async def create_ticket(self, ticket: NewTicket) -> Ticket:
        number = max(self.tickets, default=FIRST_TICKET_NUMBER - 1) + 1
        order = self.orders.get(ticket.order_number) if ticket.order_number else None
        now = datetime.now(UTC)
        created = Ticket(
            **ticket.model_dump(),
            number=number,
            status="open",
            customer_id=order.customer_id if order else None,
            created_at=now,
            updated_at=now,
        )
        self.tickets[number] = created
        self.notes[number] = []
        return created

    async def add_note(
        self,
        number: int,
        author: NoteAuthor,
        body: str,
        conversation_id: UUID | None,
        priority: Priority | None = None,
    ) -> Ticket:
        ticket = self.tickets.get(number)
        if ticket is None:
            raise LookupError(f"No ticket {number}")
        now = datetime.now(UTC)
        self.notes[number].append(Note(author=author, body=body, created_at=now))
        changes: dict[str, object] = {"updated_at": now}
        if ticket.status == "waiting_on_customer":
            changes["status"] = "open"
        if (
            priority is not None
            and _PRIORITY_RANK[priority] > _PRIORITY_RANK[ticket.priority]
        ):
            changes["priority"] = priority
        updated = ticket.model_copy(update=changes)
        self.tickets[number] = updated
        return updated

    async def create_handover(self, handover: NewHandover) -> Handover:
        created = Handover(
            **handover.model_dump(),
            id=len(self.handovers) + 1,
            created_at=datetime.now(UTC),
        )
        self.handovers.append(created)
        return created

    async def list_tickets(
        self,
        *,
        status: TicketStatus | None = None,
        topic: Topic | None = None,
        limit: int = 100,
    ) -> list[TicketDetail]:
        return self._newest_first(
            [
                t
                for t in self.tickets.values()
                if (status is None or t.status == status)
                and (topic is None or t.topic == topic)
            ]
        )[:limit]

    async def get_ticket(self, number: int) -> TicketDetail | None:
        ticket = self.tickets.get(number)
        return self._detail(ticket) if ticket else None

    async def list_handovers(self, limit: int = 100) -> list[Handover]:
        return list(reversed(self.handovers))[:limit]
