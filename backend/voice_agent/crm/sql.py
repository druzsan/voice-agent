from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import ColumnElement, Select, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from voice_agent.crm.models import (
    CustomerRow,
    HandoverRow,
    OrderRow,
    TicketNoteRow,
    TicketRow,
    VehicleRow,
)
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

_PRIORITY_RANK = {"normal": 0, "high": 1, "urgent": 2, "safety": 3}


class SqlCrm:
    """The customer care system in PostgreSQL (schema crm), one transaction per call."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def get_order(self, order_number: str) -> Order | None:
        async with self._sessions() as session:
            row = await session.get(OrderRow, order_number)
            return Order.model_validate(row, from_attributes=True) if row else None

    async def get_customer(self, customer_id: int) -> Customer | None:
        async with self._sessions() as session:
            row = await session.get(CustomerRow, customer_id)
            return Customer.model_validate(row, from_attributes=True) if row else None

    async def search_tickets(
        self,
        *,
        number: int | None = None,
        mobile_phone: str | None = None,
        order_number: str | None = None,
        statuses: tuple[TicketStatus, ...] | None = None,
    ) -> list[TicketDetail]:
        conditions: list[ColumnElement[bool]] = []
        if number is not None:
            conditions.append(TicketRow.number == number)
        if order_number is not None:
            conditions.append(TicketRow.order_number == order_number)
        if mobile_phone is not None:
            conditions.append(TicketRow.mobile_phone == mobile_phone)
            conditions.append(
                TicketRow.customer_id.in_(
                    select(CustomerRow.id).where(
                        CustomerRow.mobile_phone == mobile_phone
                    )
                )
            )
        if not conditions:
            return []
        query = select(TicketRow).where(or_(*conditions))
        if statuses is not None:
            query = query.where(TicketRow.status.in_(statuses))
        async with self._sessions() as session:
            return await self._details(session, query)

    async def create_ticket(self, ticket: NewTicket) -> Ticket:
        async with self._sessions.begin() as session:
            customer_id = None
            if ticket.order_number is not None:
                order = await session.get(OrderRow, ticket.order_number)
                customer_id = order.customer_id if order else None
            row = TicketRow(
                **ticket.model_dump(), status="open", customer_id=customer_id
            )
            session.add(row)
            await session.flush()
            await session.refresh(row)
            return Ticket.model_validate(row, from_attributes=True)

    async def add_note(
        self,
        number: int,
        author: NoteAuthor,
        body: str,
        conversation_id: UUID | None,
        priority: Priority | None = None,
    ) -> Ticket:
        async with self._sessions.begin() as session:
            row = await session.get(TicketRow, number, with_for_update=True)
            if row is None:
                raise LookupError(f"No ticket {number}")
            session.add(
                TicketNoteRow(
                    ticket_number=number,
                    author=author,
                    body=body,
                    conversation_id=conversation_id,
                )
            )
            values: dict[str, object] = {"updated_at": func.now()}
            if row.status == "waiting_on_customer":
                values["status"] = "open"
            # Priority only ever goes up
            if priority is not None and _PRIORITY_RANK[priority] > _PRIORITY_RANK.get(
                row.priority, 0
            ):
                values["priority"] = priority
            await session.execute(
                update(TicketRow).where(TicketRow.number == number).values(**values)
            )
            await session.flush()
            await session.refresh(row)
            return Ticket.model_validate(row, from_attributes=True)

    async def create_handover(self, handover: NewHandover) -> Handover:
        async with self._sessions.begin() as session:
            row = HandoverRow(**handover.model_dump())
            session.add(row)
            await session.flush()
            await session.refresh(row)
            return Handover.model_validate(row, from_attributes=True)

    async def list_tickets(
        self,
        *,
        status: TicketStatus | None = None,
        topic: Topic | None = None,
        limit: int = 100,
    ) -> list[TicketDetail]:
        query = select(TicketRow)
        if status is not None:
            query = query.where(TicketRow.status == status)
        if topic is not None:
            query = query.where(TicketRow.topic == topic)
        async with self._sessions() as session:
            return await self._details(session, query.limit(limit))

    async def get_ticket(self, number: int) -> TicketDetail | None:
        async with self._sessions() as session:
            found = await self._details(
                session, select(TicketRow).where(TicketRow.number == number)
            )
            return found[0] if found else None

    async def list_handovers(self, limit: int = 100) -> list[Handover]:
        async with self._sessions() as session:
            rows = await session.scalars(
                select(HandoverRow)
                .order_by(HandoverRow.created_at.desc(), HandoverRow.id.desc())
                .limit(limit)
            )
            return [Handover.model_validate(row, from_attributes=True) for row in rows]

    async def _details(
        self, session: AsyncSession, query: Select[TicketRow]
    ) -> list[TicketDetail]:
        rows: Sequence[TicketRow] = (
            await session.scalars(
                query.order_by(TicketRow.updated_at.desc(), TicketRow.number.desc())
            )
        ).all()
        if not rows:
            return []
        numbers = [row.number for row in rows]
        notes: dict[int, list[Note]] = {number: [] for number in numbers}
        for note in await session.scalars(
            select(TicketNoteRow)
            .where(TicketNoteRow.ticket_number.in_(numbers))
            .order_by(TicketNoteRow.created_at, TicketNoteRow.id)
        ):
            notes[note.ticket_number].append(
                Note.model_validate(note, from_attributes=True)
            )
        customers = {
            row.id: row
            for row in await session.scalars(
                select(CustomerRow).where(
                    CustomerRow.id.in_({r.customer_id for r in rows if r.customer_id})
                )
            )
        }
        vehicles = {
            row.id: row
            for row in await session.scalars(
                select(VehicleRow).where(
                    VehicleRow.id.in_({r.vehicle_id for r in rows if r.vehicle_id})
                )
            )
        }
        orders = {
            row.order_number: row
            for row in await session.scalars(
                select(OrderRow).where(
                    OrderRow.order_number.in_(
                        {r.order_number for r in rows if r.order_number}
                    )
                )
            )
        }
        details: list[TicketDetail] = []
        for row in rows:
            customer = customers.get(row.customer_id) if row.customer_id else None
            vehicle = vehicles.get(row.vehicle_id) if row.vehicle_id else None
            order = orders.get(row.order_number) if row.order_number else None
            model = vehicle.model if vehicle else order.model if order else None
            details.append(
                TicketDetail(
                    **Ticket.model_validate(row, from_attributes=True).model_dump(),
                    customer_name=(
                        f"{customer.first_name} {customer.last_name}"
                        if customer
                        else None
                    ),
                    postal_code=customer.postal_code if customer else None,
                    vehicle_model=model,
                    notes=notes[row.number],
                )
            )
        return details
