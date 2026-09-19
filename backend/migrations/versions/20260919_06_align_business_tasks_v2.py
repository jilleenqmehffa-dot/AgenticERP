"""align business tasks with V2 model

Revision ID: 20260919_06
Revises: 20260918_05
Create Date: 2026-09-19
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260919_06"
down_revision: str | Sequence[str] | None = "20260918_05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM business_tasks WHERE assigned_employee_id IS NULL)
               OR EXISTS (
                   SELECT 1 FROM business_tasks
                   WHERE status NOT IN ('PENDING', 'COMPLETED', 'CANCELLED')
               )
               OR EXISTS (SELECT 1 FROM business_tasks WHERE created_by <> 'SYSTEM')
               OR EXISTS (SELECT 1 FROM business_tasks WHERE started_at IS NOT NULL)
               OR EXISTS (SELECT 1 FROM business_tasks WHERE status = 'CANCELLED')
               OR EXISTS (
                   SELECT 1 FROM business_tasks
                   WHERE status = 'COMPLETED'
                     AND (actual_data IS NULL OR completed_at IS NULL)
               )
               OR EXISTS (
                   SELECT 1 FROM business_tasks
                   WHERE status = 'PENDING'
                     AND (actual_data IS NOT NULL OR completed_at IS NOT NULL)
               )
            THEN
                RAISE EXCEPTION
                    'business_tasks contains rows requiring manual V2 backfill';
            END IF;
        END;
        $$
        """
    )

    op.drop_constraint("task_status", "business_tasks", type_="check")
    op.alter_column(
        "business_tasks",
        "status",
        existing_type=sa.String(length=11),
        type_=sa.String(length=9),
    )
    op.create_check_constraint(
        "task_status",
        "business_tasks",
        "status IN ('PENDING', 'COMPLETED', 'CANCELLED')",
    )
    op.alter_column(
        "business_tasks",
        "assigned_employee_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.add_column(
        "business_tasks",
        sa.Column("cancel_reason", sa.Text(), nullable=True),
    )
    op.add_column(
        "business_tasks",
        sa.Column("created_by_type", sa.String(length=8), nullable=True),
    )
    op.add_column(
        "business_tasks",
        sa.Column("created_by_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "business_tasks",
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute("UPDATE business_tasks SET created_by_type = 'SYSTEM'")
    op.alter_column(
        "business_tasks",
        "created_by_type",
        existing_type=sa.String(length=8),
        nullable=False,
    )
    op.create_check_constraint(
        "business_task_actor_type",
        "business_tasks",
        "created_by_type IN ('EMPLOYEE', 'SYSTEM', 'AGENT')",
    )
    op.drop_column("business_tasks", "created_by")
    op.drop_column("business_tasks", "started_at")


def downgrade() -> None:
    op.add_column(
        "business_tasks",
        sa.Column("created_by", sa.String(255), nullable=True),
    )
    op.execute(
        "UPDATE business_tasks "
        "SET created_by = COALESCE(created_by_id, created_by_type)"
    )
    op.alter_column(
        "business_tasks", "created_by", existing_type=sa.String(255), nullable=False
    )
    op.add_column(
        "business_tasks",
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.drop_constraint("business_task_actor_type", "business_tasks", type_="check")
    op.drop_column("business_tasks", "created_by_type")
    op.drop_column("business_tasks", "created_by_id")
    op.drop_column("business_tasks", "cancel_reason")
    op.drop_column("business_tasks", "cancelled_at")
    op.alter_column(
        "business_tasks",
        "assigned_employee_id",
        existing_type=sa.Integer(),
        nullable=True,
    )
    op.drop_constraint("task_status", "business_tasks", type_="check")
    op.alter_column(
        "business_tasks",
        "status",
        existing_type=sa.String(length=9),
        type_=sa.String(length=11),
    )
    op.create_check_constraint(
        "task_status",
        "business_tasks",
        "status IN ('PENDING', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED', 'FAILED')",
    )
