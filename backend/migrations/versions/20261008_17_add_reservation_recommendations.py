"""add reservation recommendation type and result link

Revision ID: 20261008_17
Revises: 20261003_16
Create Date: 2026-10-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261008_17"
down_revision: str | Sequence[str] | None = "20261003_16"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "task_recommendations",
        sa.Column(
            "recommendation_type",
            sa.Enum(
                "TASK",
                "RESERVATION",
                name="recommendation_type",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
            server_default="TASK",
        ),
    )
    op.alter_column(
        "task_recommendations", "task_type", existing_type=sa.String(15), nullable=True
    )
    op.add_column(
        "task_recommendations",
        sa.Column("approved_reservation_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_task_recommendations_approved_reservation_id",
        "task_recommendations",
        "stock_reservations",
        ["approved_reservation_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_task_recommendations_approved_reservation",
        "task_recommendations",
        ["approved_reservation_id"],
    )
    op.create_check_constraint(
        "ck_task_recommendations_type_source",
        "task_recommendations",
        "(recommendation_type = 'TASK' AND task_type IS NOT NULL) OR "
        "(recommendation_type = 'RESERVATION' AND task_type IS NULL "
        "AND source_type = 'OUTBOUND_ORDER_ITEM' AND source_id IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_task_recommendations_reservation_approval_complete",
        "task_recommendations",
        "recommendation_type != 'RESERVATION' OR status != 'APPROVED' "
        "OR approved_reservation_id IS NOT NULL",
    )


def downgrade() -> None:
    op.execute(
        """DO $$ BEGIN
            IF EXISTS (
                SELECT 1 FROM task_recommendations
                WHERE recommendation_type = 'RESERVATION'
            ) THEN
                RAISE EXCEPTION 'reservation recommendations cannot be downgraded';
            END IF;
        END $$"""
    )
    op.drop_constraint(
        "ck_task_recommendations_reservation_approval_complete",
        "task_recommendations",
        type_="check",
    )
    op.drop_constraint(
        "ck_task_recommendations_type_source", "task_recommendations", type_="check"
    )
    op.drop_constraint(
        "uq_task_recommendations_approved_reservation",
        "task_recommendations",
        type_="unique",
    )
    op.drop_constraint(
        "fk_task_recommendations_approved_reservation_id",
        "task_recommendations",
        type_="foreignkey",
    )
    op.drop_column("task_recommendations", "approved_reservation_id")
    op.alter_column(
        "task_recommendations", "task_type", existing_type=sa.String(15), nullable=False
    )
    op.drop_column("task_recommendations", "recommendation_type")
