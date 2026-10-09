"""add reviewed inventory adjustments

Revision ID: 20261009_18
Revises: 20261008_17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261009_18"
down_revision: str | Sequence[str] | None = "20261008_17"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "inventory_adjustments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("count_item_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("warehouse_code", sa.String(64), nullable=False),
        sa.Column("location_id", sa.Integer(), nullable=False),
        sa.Column("system_quantity", sa.Numeric(18, 3), nullable=False),
        sa.Column("counted_quantity", sa.Numeric(18, 3), nullable=False),
        sa.Column("difference_quantity", sa.Numeric(18, 3), nullable=False),
        sa.Column(
            "status",
            sa.Enum("PENDING_REVIEW", "APPLIED", "REJECTED", name="adjustment_status",
                    native_enum=False, create_constraint=True),
            nullable=False,
            server_default="PENDING_REVIEW",
        ),
        sa.Column("reviewed_by_id", sa.Integer(), nullable=True),
        sa.Column("review_reason", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("difference_quantity <> 0", name="ck_inventory_adjustments_nonzero"),
        sa.ForeignKeyConstraint(["count_item_id"], ["inventory_count_items.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["location_id"], ["warehouse_locations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reviewed_by_id"], ["employees.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_inventory_adjustments_count_item_id", "inventory_adjustments", ["count_item_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_inventory_adjustments_count_item_id", table_name="inventory_adjustments")
    op.drop_table("inventory_adjustments")
