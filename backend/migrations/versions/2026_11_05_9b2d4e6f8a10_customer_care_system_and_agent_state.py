"""customer care system and agent state

Revision ID: 9b2d4e6f8a10
Revises: 3c1e5a9d2b47
Create Date: 2026-11-05 15:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "9b2d4e6f8a10"
down_revision: str | Sequence[str] | None = "3c1e5a9d2b47"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "crm"
TOPICS = "'delivery', 'charging', 'connected_services', 'warranty'"
STATUSES = "'open', 'in_progress', 'waiting_on_customer', 'resolved', 'closed'"
PRIORITIES = "'normal', 'high', 'urgent', 'safety'"
ROUTES = (
    "'delivery', 'technical_support', 'warranty_service', 'account_security', "
    "'roadside_assistance', 'language_support', 'general'"
)
HANDOVER_STATUSES = "'transferred', 'unavailable'"
NOTE_AUTHORS = "'carrie', 'care_agent', 'system'"


def _now() -> sa.TextClause:
    return sa.text("now()")


def upgrade() -> None:
    op.add_column("conversations", sa.Column("caller_phone", sa.Text(), nullable=True))
    op.add_column("conversations", sa.Column("language", sa.Text(), nullable=True))
    op.add_column(
        "conversations",
        sa.Column("state", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "messages",
        sa.Column(
            "model_messages", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
    )
    op.add_column(
        "messages",
        sa.Column("tool_calls", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )

    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
    op.create_table(
        "customers",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("first_name", sa.Text(), nullable=False),
        sa.Column("last_name", sa.Text(), nullable=False),
        sa.Column("postal_code", sa.Text(), nullable=False),
        sa.Column("city", sa.Text(), nullable=False),
        sa.Column("mobile_phone", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("preferred_language", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_customers")),
        schema=SCHEMA,
    )
    op.create_index(
        op.f("ix_crm_customers_mobile_phone"),
        "customers",
        ["mobile_phone"],
        schema=SCHEMA,
    )
    op.create_table(
        "vehicles",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("vin", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("model_year", sa.Integer(), nullable=False),
        sa.Column("powertrain", sa.Text(), nullable=False),
        sa.Column("first_registration", sa.Date(), nullable=True),
        sa.Column("mileage_km", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            [f"{SCHEMA}.customers.id"],
            name=op.f("fk_vehicles_customer_id_customers"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_vehicles")),
        sa.UniqueConstraint("vin", name=op.f("uq_vehicles_vin")),
        schema=SCHEMA,
    )
    op.create_table(
        "orders",
        sa.Column("order_number", sa.Text(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("ordered_on", sa.Date(), nullable=False),
        sa.Column("confirmed_delivery_date", sa.Date(), nullable=True),
        sa.Column("estimate_from", sa.Date(), nullable=True),
        sa.Column("estimate_to", sa.Date(), nullable=True),
        sa.Column("previous_estimate_from", sa.Date(), nullable=True),
        sa.Column("previous_estimate_to", sa.Date(), nullable=True),
        sa.Column("status_reason", sa.Text(), nullable=True),
        sa.Column("dealer", sa.Text(), nullable=False),
        sa.Column("status_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            [f"{SCHEMA}.customers.id"],
            name=op.f("fk_orders_customer_id_customers"),
        ),
        sa.PrimaryKeyConstraint("order_number", name=op.f("pk_orders")),
        schema=SCHEMA,
    )
    op.create_table(
        "tickets",
        sa.Column(
            "number",
            sa.Integer(),
            sa.Identity(always=False, start=10001),
            nullable=False,
        ),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column("issue_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("priority", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("vehicle_id", sa.Integer(), nullable=True),
        sa.Column("order_number", sa.Text(), nullable=True),
        sa.Column("mobile_phone", sa.Text(), nullable=True),
        sa.Column("verification_status", sa.Text(), nullable=False),
        sa.Column("language", sa.Text(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=_now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=_now(),
            nullable=False,
        ),
        sa.CheckConstraint(f"topic IN ({TOPICS})", name=op.f("ck_tickets_topic")),
        sa.CheckConstraint(f"status IN ({STATUSES})", name=op.f("ck_tickets_status")),
        sa.CheckConstraint(
            f"priority IN ({PRIORITIES})", name=op.f("ck_tickets_priority")
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            [f"{SCHEMA}.customers.id"],
            name=op.f("fk_tickets_customer_id_customers"),
        ),
        sa.ForeignKeyConstraint(
            ["vehicle_id"],
            [f"{SCHEMA}.vehicles.id"],
            name=op.f("fk_tickets_vehicle_id_vehicles"),
        ),
        sa.PrimaryKeyConstraint("number", name=op.f("pk_tickets")),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_crm_tickets_customer_id", "tickets", ["customer_id"], schema=SCHEMA
    )
    op.create_table(
        "ticket_notes",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("ticket_number", sa.Integer(), nullable=False),
        sa.Column("author", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=_now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            f"author IN ({NOTE_AUTHORS})", name=op.f("ck_ticket_notes_author")
        ),
        sa.ForeignKeyConstraint(
            ["ticket_number"],
            [f"{SCHEMA}.tickets.number"],
            name=op.f("fk_ticket_notes_ticket_number_tickets"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ticket_notes")),
        schema=SCHEMA,
    )
    op.create_index(
        op.f("ix_crm_ticket_notes_ticket_number"),
        "ticket_notes",
        ["ticket_number"],
        schema=SCHEMA,
    )
    op.create_table(
        "handovers",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=True),
        sa.Column("ticket_number", sa.Integer(), nullable=True),
        sa.Column("route", sa.Text(), nullable=False),
        sa.Column("priority", sa.Text(), nullable=False),
        sa.Column("language", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=_now(),
            nullable=False,
        ),
        sa.CheckConstraint(f"route IN ({ROUTES})", name=op.f("ck_handovers_route")),
        sa.CheckConstraint(
            f"priority IN ({PRIORITIES})", name=op.f("ck_handovers_priority")
        ),
        sa.CheckConstraint(
            f"status IN ({HANDOVER_STATUSES})", name=op.f("ck_handovers_status")
        ),
        sa.ForeignKeyConstraint(
            ["ticket_number"],
            [f"{SCHEMA}.tickets.number"],
            name=op.f("fk_handovers_ticket_number_tickets"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_handovers")),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.execute(f"DROP SCHEMA {SCHEMA} CASCADE")
    op.drop_column("messages", "tool_calls")
    op.drop_column("messages", "model_messages")
    op.drop_column("conversations", "state")
    op.drop_column("conversations", "language")
    op.drop_column("conversations", "caller_phone")
