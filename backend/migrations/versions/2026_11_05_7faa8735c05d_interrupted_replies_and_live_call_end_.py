"""interrupted replies and live call end reasons

Revision ID: 7faa8735c05d
Revises: 717f63f24596
Create Date: 2026-11-05 12:28:11.540952
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7faa8735c05d"
down_revision: str | Sequence[str] | None = "717f63f24596"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


END_REASONS = "'hangup', 'page_closed'"
LIVE_CALL_END_REASONS = f"{END_REASONS}, 'disconnect', 'timeout', 'error'"


def _end_reasons(values: str) -> None:
    # Autogenerate doesn't compare CHECK constraints; replaced by hand
    op.drop_constraint(
        op.f("ck_conversations_end_reason"), "conversations", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_conversations_end_reason"),
        "conversations",
        f"end_reason IN ({values})",
    )


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column(
            "interrupted", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
    )
    op.add_column("messages", sa.Column("heard_text", sa.Text(), nullable=True))
    _end_reasons(LIVE_CALL_END_REASONS)


def downgrade() -> None:
    # Calls that ended the new ways keep their end, without a reason
    op.execute(
        "UPDATE conversations SET end_reason = NULL"
        f" WHERE end_reason NOT IN ({END_REASONS})"
    )
    _end_reasons(END_REASONS)
    op.drop_column("messages", "heard_text")
    op.drop_column("messages", "interrupted")
