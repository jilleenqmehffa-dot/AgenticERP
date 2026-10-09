"""size inventory workflow enum columns to their longest values

Revision ID: 20261009_21
Revises: 20261009_20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261009_21"
down_revision: str | Sequence[str] | None = "20261009_20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "business_tasks", "task_type",
        existing_type=sa.String(24), type_=sa.String(22),
    )
    op.alter_column(
        "task_recommendations", "task_type",
        existing_type=sa.String(24), type_=sa.String(22), existing_nullable=True,
    )
    op.alter_column(
        "inventory_adjustments", "status",
        existing_type=sa.String(14), type_=sa.String(15),
    )


def downgrade() -> None:
    op.alter_column(
        "inventory_adjustments", "status",
        existing_type=sa.String(15), type_=sa.String(14),
    )
    op.alter_column(
        "task_recommendations", "task_type",
        existing_type=sa.String(22), type_=sa.String(24), existing_nullable=True,
    )
    op.alter_column(
        "business_tasks", "task_type",
        existing_type=sa.String(22), type_=sa.String(24),
    )
