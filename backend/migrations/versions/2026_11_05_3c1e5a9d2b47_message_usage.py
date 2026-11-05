"""message usage

Revision ID: 3c1e5a9d2b47
Revises: 7faa8735c05d
Create Date: 2026-11-05 16:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "3c1e5a9d2b47"
down_revision: str | Sequence[str] | None = "7faa8735c05d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("usage", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("messages", "usage")
