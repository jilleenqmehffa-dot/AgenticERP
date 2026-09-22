"""align status column lengths after removing partial states

Revision ID: 20260921_09
Revises: 20260921_08
Create Date: 2026-09-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260921_09"
down_revision: str | Sequence[str] | None = "20260921_08"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "sales_orders",
        "status",
        existing_type=sa.String(length=19),
        type_=sa.String(length=9),
    )
    for table_name in ("account_receivables", "account_payables"):
        op.alter_column(
            table_name,
            "status",
            existing_type=sa.String(length=14),
            type_=sa.String(length=7),
        )


def downgrade() -> None:
    for table_name in ("account_receivables", "account_payables"):
        op.alter_column(
            table_name,
            "status",
            existing_type=sa.String(length=7),
            type_=sa.String(length=14),
        )
    op.alter_column(
        "sales_orders",
        "status",
        existing_type=sa.String(length=9),
        type_=sa.String(length=19),
    )
