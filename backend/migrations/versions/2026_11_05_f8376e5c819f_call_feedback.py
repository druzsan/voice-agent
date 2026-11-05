"""call feedback

Revision ID: f8376e5c819f
Revises: 9b2d4e6f8a10
Create Date: 2026-11-05 14:53:19.936485
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f8376e5c819f"
down_revision: str | Sequence[str] | None = "9b2d4e6f8a10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversations", sa.Column("feedback_rating", sa.Text(), nullable=True)
    )
    op.add_column(
        "conversations", sa.Column("feedback_comment", sa.Text(), nullable=True)
    )
    op.add_column(
        "conversations",
        sa.Column("feedback_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Autogenerate doesn't compare CHECK constraints; added by hand
    op.create_check_constraint(
        op.f("ck_conversations_feedback_rating"),
        "conversations",
        "feedback_rating IN ('up', 'down')",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_conversations_feedback_rating"), "conversations", type_="check"
    )
    op.drop_column("conversations", "feedback_at")
    op.drop_column("conversations", "feedback_comment")
    op.drop_column("conversations", "feedback_rating")
