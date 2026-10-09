"""require inventory adjustment creation timestamp

Revision ID: 20261009_19
Revises: 20261009_18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261009_19"
down_revision: str | Sequence[str] | None = "20261009_18"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "inventory_adjustments", "created_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "inventory_adjustments", "created_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=True,
    )
