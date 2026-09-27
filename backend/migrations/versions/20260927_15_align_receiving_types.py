"""align receiving and putaway column types

Revision ID: 20260927_15
Revises: 20260927_14
Create Date: 2026-09-27
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260927_15"
down_revision: str | Sequence[str] | None = "20260927_14"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "inbound_receipts",
        "status",
        existing_type=sa.String(length=18),
        type_=sa.String(length=15),
    )
    op.alter_column(
        "inventory_buckets",
        "stock_status",
        existing_type=sa.String(length=11),
        type_=sa.String(length=15),
    )
    op.alter_column(
        "business_task_items",
        "source_bucket_id",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
    )
    for column_name in (
        "id",
        "inbound_receipt_item_id",
        "business_task_id",
        "inspected_by_id",
    ):
        op.alter_column(
            "receipt_inspections",
            column_name,
            existing_type=sa.BigInteger(),
            type_=sa.Integer(),
        )


def downgrade() -> None:
    op.execute(
        "UPDATE inventory_buckets SET stock_status = 'AVAILABLE' "
        "WHERE stock_status = 'PENDING_PUTAWAY'"
    )
    for column_name in (
        "id",
        "inbound_receipt_item_id",
        "business_task_id",
        "inspected_by_id",
    ):
        op.alter_column(
            "receipt_inspections",
            column_name,
            existing_type=sa.Integer(),
            type_=sa.BigInteger(),
        )
    op.alter_column(
        "business_task_items",
        "source_bucket_id",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
    )
    op.alter_column(
        "inventory_buckets",
        "stock_status",
        existing_type=sa.String(length=15),
        type_=sa.String(length=11),
    )
    op.alter_column(
        "inbound_receipts",
        "status",
        existing_type=sa.String(length=15),
        type_=sa.String(length=18),
    )
