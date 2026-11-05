"""The care desk: tickets and handovers as the customer care team sees them."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from voice_agent.crm.matching import digits
from voice_agent.crm.records import Handover, TicketDetail, TicketStatus, Topic
from voice_agent.services import ServicesDep

router = APIRouter(prefix="/desk", tags=["desk"])


@router.get("/tickets")
async def list_tickets(
    services: ServicesDep,
    status_: Annotated[TicketStatus | None, Query(alias="status")] = None,
    topic: Topic | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> list[TicketDetail]:
    """Tickets, most recently updated first."""
    return await services.crm.list_tickets(status=status_, topic=topic, limit=limit)


@router.get("/tickets/{reference}")
async def get_ticket(services: ServicesDep, reference: str) -> TicketDetail:
    number = digits(reference)
    ticket = await services.crm.get_ticket(int(number)) if number else None
    if ticket is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such ticket")
    return ticket


@router.get("/handovers")
async def list_handovers(
    services: ServicesDep, limit: Annotated[int, Query(ge=1, le=500)] = 100
) -> list[Handover]:
    """Transfers to colleagues, newest first."""
    return await services.crm.list_handovers(limit)
