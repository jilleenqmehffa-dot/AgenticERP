"""add reservation bucket identity

Revision ID: 20260926_12
Revises: 20260922_11
Create Date: 2026-09-26
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260926_12"
down_revision: str | Sequence[str] | None = "20260922_11"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "stock_reservations",
        sa.Column("location_code", sa.String(length=64), server_default="", nullable=False),
    )
    op.add_column(
        "stock_reservations",
        sa.Column("lot_no", sa.String(length=100), server_default="", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("stock_reservations", "lot_no")
    op.drop_column("stock_reservations", "location_code")
