from datetime import date
from uuid import uuid4

import pytest

from voice_agent.config import Settings
from voice_agent.crm.records import NewHandover, NewTicket
from voice_agent.crm.seed import seed
from voice_agent.crm.sql import SqlCrm

pytestmark = pytest.mark.anyio


async def test_the_starting_data_has_five_cases_per_topic(crm: SqlCrm) -> None:
    tickets = await crm.list_tickets(limit=500)

    assert len(tickets) == 20
    for topic in ("delivery", "charging", "connected_services", "warranty"):
        assert sum(t.topic == topic for t in tickets) == 5
    assert {t.reference for t in tickets} == {f"CC-{n}" for n in range(10001, 10021)}


async def test_dates_are_relative_to_the_seeding_day(crm: SqlCrm) -> None:
    order = await crm.get_order("456789")

    assert order is not None
    assert order.confirmed_delivery_date == date(2026, 11, 10)


async def test_seeding_again_keeps_existing_data(
    crm: SqlCrm, database_url: str
) -> None:
    settings = Settings(database_url=database_url)  # pyright: ignore[reportArgumentType]

    assert not await seed(settings, reset=False)
    assert len(await crm.list_tickets(limit=500)) == 20


async def test_tickets_are_found_by_the_customers_phone(crm: SqlCrm) -> None:
    found = await crm.search_tickets(
        mobile_phone="+4915122000201", statuses=("open", "in_progress")
    )

    assert [t.reference for t in found] == ["CC-10006"]
    assert found[0].customer_name == "Markus Hoffmann"
    assert found[0].postal_code == "60311"
    assert found[0].vehicle_model == "BMW iX xDrive45"
    assert found[0].notes[-1].author == "care_agent"


async def test_a_new_ticket_is_linked_to_the_orders_customer(crm: SqlCrm) -> None:
    ticket = await crm.create_ticket(
        NewTicket(
            topic="delivery",
            issue_type="delivery_delay",
            priority="high",
            summary="Needs a replacement car.",
            details={"lease_end": "tomorrow"},
            order_number="527713",
            mobile_phone="+4915199990000",
            verification_status="order_verified",
            language="de",
            conversation_id=uuid4(),
        )
    )

    assert ticket.reference == "CC-10021"
    assert ticket.status == "open"
    detail = await crm.get_ticket(ticket.number)
    assert detail is not None and detail.customer_name == "Katrin Weber"


async def test_a_note_reopens_and_only_raises_priority(crm: SqlCrm) -> None:
    raised = await crm.add_note(10005, "carrie", "Dealer letter sent.", None, "high")
    kept = await crm.add_note(10005, "carrie", "Calm again.", None, "normal")

    assert (raised.status, raised.priority) == ("open", "high")
    assert kept.priority == "high"
    detail = await crm.get_ticket(10005)
    assert detail is not None
    assert [n.body for n in detail.notes][-2:] == ["Dealer letter sent.", "Calm again."]


async def test_handovers_are_listed_newest_first(crm: SqlCrm) -> None:
    for route in ("delivery", "technical_support"):
        await crm.create_handover(
            NewHandover(
                conversation_id=None,
                ticket_number=None,
                route=route,
                priority="normal",
                language="en",
                reason="Caller asked for a person",
                summary="Language: English. Test.",
                details={},
                status="transferred",
            )
        )

    assert [h.route for h in await crm.list_handovers()] == [
        "technical_support",
        "delivery",
    ]
