"""add inventory count review and adjustment task chain

Revision ID: 20261009_20
Revises: 20261009_19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261009_20"
down_revision: str | Sequence[str] | None = "20261009_19"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TASK_TYPES = (
    "'RECEIVE', 'PUTAWAY', 'PICK', 'PACK', 'STOCK_IN', 'STOCK_OUT', "
    "'TRANSFER', 'INVENTORY_COUNT', 'INVENTORY_COUNT_REVIEW', 'INVENTORY_ADJUSTMENT'"
)


def upgrade() -> None:
    op.drop_constraint("task_type", "business_tasks", type_="check")
    op.alter_column("business_tasks", "task_type", existing_type=sa.String(15), type_=sa.String(24))
    op.create_check_constraint("task_type", "business_tasks", f"task_type IN ({_TASK_TYPES})")
    op.drop_constraint("recommendation_task_type", "task_recommendations", type_="check")
    op.alter_column(
        "task_recommendations", "task_type", existing_type=sa.String(15),
        type_=sa.String(24), existing_nullable=True,
    )
    op.create_check_constraint(
        "recommendation_task_type", "task_recommendations",
        f"task_type IN ({_TASK_TYPES})",
    )
    op.drop_constraint("adjustment_status", "inventory_adjustments", type_="check")
    op.create_check_constraint(
        "adjustment_status", "inventory_adjustments",
        "status IN ('PENDING_REVIEW', 'READY_TO_ADJUST', 'APPLIED', 'REJECTED')",
    )
    op.add_column("inventory_adjustments", sa.Column("review_task_id", sa.Integer(), nullable=True))
    op.add_column("inventory_adjustments", sa.Column("adjustment_task_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_inventory_adjustments_review_task_id", "inventory_adjustments", "business_tasks",
        ["review_task_id"], ["id"], ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_inventory_adjustments_adjustment_task_id", "inventory_adjustments", "business_tasks",
        ["adjustment_task_id"], ["id"], ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_inventory_adjustments_review_task_id", "inventory_adjustments", ["review_task_id"]
    )
    op.create_unique_constraint(
        "uq_inventory_adjustments_adjustment_task_id", "inventory_adjustments", ["adjustment_task_id"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_inventory_adjustments_adjustment_task_id", "inventory_adjustments", type_="unique")
    op.drop_constraint("uq_inventory_adjustments_review_task_id", "inventory_adjustments", type_="unique")
    op.drop_constraint("fk_inventory_adjustments_adjustment_task_id", "inventory_adjustments", type_="foreignkey")
    op.drop_constraint("fk_inventory_adjustments_review_task_id", "inventory_adjustments", type_="foreignkey")
    op.drop_column("inventory_adjustments", "adjustment_task_id")
    op.drop_column("inventory_adjustments", "review_task_id")
    op.drop_constraint("adjustment_status", "inventory_adjustments", type_="check")
    op.create_check_constraint(
        "adjustment_status", "inventory_adjustments",
        "status IN ('PENDING_REVIEW', 'APPLIED', 'REJECTED')",
    )
    op.drop_constraint("recommendation_task_type", "task_recommendations", type_="check")
    op.alter_column(
        "task_recommendations", "task_type", existing_type=sa.String(24),
        type_=sa.String(15), existing_nullable=True,
    )
    old_types = _TASK_TYPES.replace(
        ", 'INVENTORY_COUNT_REVIEW', 'INVENTORY_ADJUSTMENT'", ""
    )
    op.create_check_constraint("recommendation_task_type", "task_recommendations", f"task_type IN ({old_types})")
    op.drop_constraint("task_type", "business_tasks", type_="check")
    op.alter_column("business_tasks", "task_type", existing_type=sa.String(24), type_=sa.String(15))
    op.create_check_constraint("task_type", "business_tasks", f"task_type IN ({old_types})")
