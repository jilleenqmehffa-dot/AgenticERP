"""add outbound packing progress

Revision ID: 20260926_13
Revises: 20260926_12
Create Date: 2026-09-26
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260926_13"
down_revision: str | Sequence[str] | None = "20260926_12"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "outbound_order_items",
        sa.Column("packed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("outbound_order_items", "packed_at")
