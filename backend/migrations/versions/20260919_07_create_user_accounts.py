"""create user accounts

Revision ID: 20260919_07
Revises: 20260919_06
Create Date: 2026-09-19
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260919_07"
down_revision: str | Sequence[str] | None = "20260919_06"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_accounts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["employee_id"],
            ["employees.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_user_accounts_employee_id",
        "user_accounts",
        ["employee_id"],
        unique=True,
    )
    op.create_index(
        "ix_user_accounts_username",
        "user_accounts",
        ["username"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_user_accounts_username", table_name="user_accounts")
    op.drop_index("ix_user_accounts_employee_id", table_name="user_accounts")
    op.drop_table("user_accounts")
