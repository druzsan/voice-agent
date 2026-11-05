"""The customer care system's tables, in their own PostgreSQL schema `crm`.

They share the app's database and migrations, but nothing else: the agent
reaches them only through the `Crm` port (voice_agent.crm.port).
"""

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Identity, Index, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from voice_agent.crm.records import (
    HANDOVER_STATUSES,
    NOTE_AUTHORS,
    PRIORITIES,
    ROUTES,
    TICKET_STATUSES,
    TOPICS,
)
from voice_agent.db.base import Base

SCHEMA = "crm"
# Tickets are numbered from here; their reference is "CC-<number>"
FIRST_TICKET_NUMBER = 10001


def _one_of(column: str, values: tuple[str, ...]) -> str:
    listed = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({listed})"


class CustomerRow(Base):
    __tablename__ = "customers"
    __table_args__ = ({"schema": SCHEMA},)

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    first_name: Mapped[str] = mapped_column(Text)
    last_name: Mapped[str] = mapped_column(Text)
    postal_code: Mapped[str] = mapped_column(Text)
    city: Mapped[str] = mapped_column(Text)
    # E.164, e.g. +4915112345678
    mobile_phone: Mapped[str] = mapped_column(Text, index=True)
    email: Mapped[str] = mapped_column(Text)
    preferred_language: Mapped[str] = mapped_column(Text)


class VehicleRow(Base):
    __tablename__ = "vehicles"
    __table_args__ = ({"schema": SCHEMA},)

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.customers.id"))
    vin: Mapped[str] = mapped_column(Text, unique=True)
    model: Mapped[str] = mapped_column(Text)
    model_year: Mapped[int]
    # bev, phev or ice
    powertrain: Mapped[str] = mapped_column(Text)
    first_registration: Mapped[date | None]
    mileage_km: Mapped[int | None]


class OrderRow(Base):
    __tablename__ = "orders"
    __table_args__ = ({"schema": SCHEMA},)

    order_number: Mapped[str] = mapped_column(Text, primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.customers.id"))
    model: Mapped[str] = mapped_column(Text)
    # ordered, in_production, in_transit, at_dealer, delivered
    status: Mapped[str] = mapped_column(Text)
    ordered_on: Mapped[date]
    confirmed_delivery_date: Mapped[date | None]
    estimate_from: Mapped[date | None]
    estimate_to: Mapped[date | None]
    previous_estimate_from: Mapped[date | None]
    previous_estimate_to: Mapped[date | None]
    # Only a reason the system recorded; None means none is known
    status_reason: Mapped[str | None] = mapped_column(Text)
    dealer: Mapped[str] = mapped_column(Text)
    status_updated_at: Mapped[datetime]


class TicketRow(Base):
    __tablename__ = "tickets"
    __table_args__ = (
        CheckConstraint(_one_of("topic", TOPICS), name="topic"),
        CheckConstraint(_one_of("status", TICKET_STATUSES), name="status"),
        CheckConstraint(_one_of("priority", PRIORITIES), name="priority"),
        Index("ix_crm_tickets_customer_id", "customer_id"),
        {"schema": SCHEMA},
    )

    number: Mapped[int] = mapped_column(
        Identity(start=FIRST_TICKET_NUMBER), primary_key=True
    )
    topic: Mapped[str] = mapped_column(Text)
    issue_type: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text)
    # Topic-specific facts (the optional handover fields of the specs)
    details: Mapped[dict[str, Any]] = mapped_column(default=dict)
    customer_id: Mapped[int | None] = mapped_column(
        ForeignKey(f"{SCHEMA}.customers.id")
    )
    vehicle_id: Mapped[int | None] = mapped_column(ForeignKey(f"{SCHEMA}.vehicles.id"))
    order_number: Mapped[str | None] = mapped_column(Text)
    mobile_phone: Mapped[str | None] = mapped_column(Text)
    # unverified, order_verified, ticket_verified
    verification_status: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(Text)
    # The call that created it; no foreign key, the CRM stands on its own
    conversation_id: Mapped[UUID | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())


class TicketNoteRow(Base):
    __tablename__ = "ticket_notes"
    __table_args__ = (
        CheckConstraint(_one_of("author", NOTE_AUTHORS), name="author"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    ticket_number: Mapped[int] = mapped_column(
        ForeignKey(f"{SCHEMA}.tickets.number", ondelete="CASCADE"), index=True
    )
    author: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    conversation_id: Mapped[UUID | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class HandoverRow(Base):
    __tablename__ = "handovers"
    __table_args__ = (
        CheckConstraint(_one_of("route", ROUTES), name="route"),
        CheckConstraint(_one_of("priority", PRIORITIES), name="priority"),
        CheckConstraint(_one_of("status", HANDOVER_STATUSES), name="status"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    conversation_id: Mapped[UUID | None]
    ticket_number: Mapped[int | None] = mapped_column(
        ForeignKey(f"{SCHEMA}.tickets.number")
    )
    route: Mapped[str] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(Text)
    # The conversation's language: the colleague who takes over speaks it
    language: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text)
    # Structured context: caller number, verified facts, other issues, ...
    details: Mapped[dict[str, Any]] = mapped_column(default=dict)
    status: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
