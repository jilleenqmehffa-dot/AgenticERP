"""create business tasks

Revision ID: 20260918_04
Revises: 20260918_03
Create Date: 2026-09-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260918_04"
down_revision: str | Sequence[str] | None = "20260918_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "business_tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_no", sa.String(length=64), nullable=False),
        sa.Column(
            "task_type",
            sa.Enum(
                "STOCK_IN",
                "STOCK_OUT",
                name="task_type",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "IN_PROGRESS",
                "COMPLETED",
                "CANCELLED",
                "FAILED",
                name="task_status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="PENDING",
            nullable=False,
        ),
        sa.Column("assigned_employee_id", sa.Integer(), nullable=True),
        sa.Column("source_type", sa.String(length=64), nullable=True),
        sa.Column("source_id", sa.BigInteger(), nullable=True),
        sa.Column("planned_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("actual_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("exception_reason", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(source_type IS NULL) = (source_id IS NULL)",
            name="ck_business_tasks_source_complete",
        ),
        sa.ForeignKeyConstraint(
            ["assigned_employee_id"],
            ["employees.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_business_tasks_assigned_employee_id",
        "business_tasks",
        ["assigned_employee_id"],
    )
    op.create_index(
        "ix_business_tasks_source",
        "business_tasks",
        ["source_type", "source_id"],
    )
    op.create_index(
        "ix_business_tasks_task_no",
        "business_tasks",
        ["task_no"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_business_tasks_task_no", table_name="business_tasks")
    op.drop_index("ix_business_tasks_source", table_name="business_tasks")
    op.drop_index(
        "ix_business_tasks_assigned_employee_id",
        table_name="business_tasks",
    )
    op.drop_table("business_tasks")
