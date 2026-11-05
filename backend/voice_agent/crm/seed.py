"""Loads the starting data into the customer care system.

python -m voice_agent.crm.seed           # only into an empty system
python -m voice_agent.crm.seed --reset   # deletes all CRM data first
"""

import argparse
import asyncio
import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from voice_agent.config import Settings
from voice_agent.crm.models import (
    SCHEMA,
    CustomerRow,
    OrderRow,
    TicketNoteRow,
    TicketRow,
    VehicleRow,
)
from voice_agent.crm.seed_data import CASES, SeedCase, day, moment
from voice_agent.db.repository import create_engine

logger = logging.getLogger(__name__)

_TABLES = ("handovers", "ticket_notes", "tickets", "orders", "vehicles", "customers")


async def _add_case(session: AsyncSession, case: SeedCase, today: date) -> None:
    c = case.customer
    customer = CustomerRow(
        first_name=c.first_name,
        last_name=c.last_name,
        postal_code=c.postal_code,
        city=c.city,
        mobile_phone=c.mobile_phone,
        email=c.email,
        preferred_language=c.preferred_language,
    )
    session.add(customer)
    await session.flush()

    vehicle_id = None
    if (v := case.vehicle) is not None:
        vehicle = VehicleRow(
            customer_id=customer.id,
            vin=v.vin,
            model=v.model,
            model_year=v.model_year,
            powertrain=v.powertrain,
            first_registration=(
                day(today, -v.registered_days_ago) if v.registered_days_ago else None
            ),
            mileage_km=v.mileage_km,
        )
        session.add(vehicle)
        await session.flush()
        vehicle_id = vehicle.id

    if (o := case.order) is not None:
        estimate = o.estimate_in_days
        previous = o.previous_estimate_in_days
        confirmed = o.confirmed_in_days
        session.add(
            OrderRow(
                order_number=o.order_number,
                customer_id=customer.id,
                model=o.model,
                status=o.status,
                ordered_on=day(today, -o.ordered_days_ago),
                confirmed_delivery_date=(
                    day(today, confirmed) if confirmed is not None else None
                ),
                estimate_from=day(today, estimate[0]) if estimate else None,
                estimate_to=day(today, estimate[1]) if estimate else None,
                previous_estimate_from=day(today, previous[0]) if previous else None,
                previous_estimate_to=day(today, previous[1]) if previous else None,
                status_reason=o.status_reason,
                dealer=o.dealer,
                status_updated_at=moment(today, o.status_updated_days_ago, hour=8),
            )
        )

    t = case.ticket
    created = moment(today, t.created_days_ago)
    updated = max([created, *(moment(today, n.days_ago, hour=15) for n in t.notes)])
    ticket = TicketRow(
        topic=t.topic,
        issue_type=t.issue_type,
        status=t.status,
        priority=t.priority,
        summary=t.summary,
        details=t.details,
        customer_id=customer.id,
        vehicle_id=vehicle_id,
        order_number=case.order.order_number if case.order else None,
        mobile_phone=c.mobile_phone,
        verification_status="order_verified" if case.order else "unverified",
        language=c.preferred_language,
        created_at=created,
        updated_at=updated,
    )
    session.add(ticket)
    await session.flush()
    for note in t.notes:
        session.add(
            TicketNoteRow(
                ticket_number=ticket.number,
                author=note.author,
                body=note.body,
                created_at=moment(today, note.days_ago, hour=15),
            )
        )


async def seed(settings: Settings, *, reset: bool, today: date | None = None) -> bool:
    """Loads the cases; returns False when the system had data and wasn't reset."""
    today = today or datetime.now(ZoneInfo("Europe/Berlin")).date()
    engine = create_engine(settings.database_url.get_secret_value())
    try:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions.begin() as session:
            if reset:
                tables = ", ".join(f"{SCHEMA}.{name}" for name in _TABLES)
                await session.execute(
                    text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE")
                )
            elif await session.scalar(select(func.count(CustomerRow.id))):
                return False
            for case in CASES:
                await _add_case(session, case, today)
        return True
    finally:
        await engine.dispose()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument(
        "--reset", action="store_true", help="delete all CRM data before loading"
    )
    arguments = parser.parse_args()
    if asyncio.run(seed(Settings(), reset=arguments.reset)):
        logger.info("Loaded %d customer care cases", len(CASES))
    else:
        logger.info("The customer care system already has data; use --reset to reload")


if __name__ == "__main__":
    main()
