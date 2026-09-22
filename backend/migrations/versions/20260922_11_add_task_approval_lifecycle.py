"""add task recommendation, review, and execution lifecycle

Revision ID: 20260922_11
Revises: 20260921_10
Create Date: 2026-09-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260922_11"
down_revision: str | Sequence[str] | None = "20260921_10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("task_status", "business_tasks", type_="check")
    op.alter_column(
        "business_tasks",
        "status",
        existing_type=sa.String(length=9),
        type_=sa.String(length=22),
        server_default=None,
    )
    op.execute("UPDATE business_tasks SET status = 'ASSIGNED' WHERE status = 'PENDING'")
    op.execute(
        "UPDATE business_tasks SET status = 'EXECUTION_FAILED' WHERE status = 'FAILED'"
    )
    op.create_check_constraint(
        "task_status",
        "business_tasks",
        "status IN ("
        "'ASSIGNED', 'IN_PROGRESS', 'PENDING_REVIEW', 'CHANGES_REQUESTED', "
        "'APPROVED_FOR_EXECUTION', 'EXECUTING', 'COMPLETED', "
        "'EXECUTION_FAILED', 'CANCELLED'"
        ")",
    )
    op.alter_column(
        "business_tasks",
        "status",
        existing_type=sa.String(length=22),
        server_default="ASSIGNED",
    )

    op.create_table(
        "task_recommendations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("recommendation_no", sa.String(length=64), nullable=False),
        sa.Column(
            "task_type",
            sa.Enum(
                "RECEIVE", "PUTAWAY", "PICK", "PACK", "STOCK_IN", "STOCK_OUT",
                "TRANSFER", "INVENTORY_COUNT", name="recommendation_task_type",
                native_enum=False, create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("warehouse_id", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=True),
        sa.Column("source_id", sa.BigInteger(), nullable=True),
        sa.Column("proposed_assignee_id", sa.Integer(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column(
            "proposed_data", postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"), nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "SUGGESTED", "APPROVED", "REJECTED", "EXPIRED",
                name="recommendation_status", native_enum=False,
                create_constraint=True,
            ),
            server_default="SUGGESTED", nullable=False,
        ),
        sa.Column(
            "suggested_by_type",
            sa.Enum(
                "EMPLOYEE", "SYSTEM", "AGENT", name="recommendation_actor_type",
                native_enum=False, create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("suggested_by_id", sa.String(length=255), nullable=False),
        sa.Column("reviewed_by_id", sa.Integer(), nullable=True),
        sa.Column("review_reason", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_task_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.CheckConstraint(
            "(source_type IS NULL) = (source_id IS NULL)",
            name="ck_task_recommendations_source_complete",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_task_recommendations_confidence_range",
        ),
        sa.ForeignKeyConstraint(["warehouse_id"], ["warehouses.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["proposed_assignee_id"], ["employees.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_id"], ["employees.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["approved_task_id"], ["business_tasks.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "approved_task_id", name="uq_task_recommendations_approved_task"
        ),
    )
    op.create_index(
        "ix_task_recommendations_recommendation_no", "task_recommendations",
        ["recommendation_no"], unique=True,
    )
    op.create_index(
        "ix_task_recommendations_warehouse_id", "task_recommendations", ["warehouse_id"]
    )
    op.create_index(
        "ix_task_recommendations_proposed_assignee_id", "task_recommendations",
        ["proposed_assignee_id"],
    )
    op.create_index(
        "ix_task_recommendations_reviewed_by_id", "task_recommendations",
        ["reviewed_by_id"],
    )
    op.create_index(
        "ix_task_recommendations_source", "task_recommendations",
        ["source_type", "source_id"],
    )

    op.create_table(
        "task_submissions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING_REVIEW", "APPROVED", "CHANGES_REQUESTED", "WITHDRAWN",
                name="submission_status", native_enum=False, create_constraint=True,
            ),
            server_default="PENDING_REVIEW", nullable=False,
        ),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("submitted_by_id", sa.Integer(), nullable=False),
        sa.Column(
            "submitted_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column("reviewed_by_id", sa.Integer(), nullable=True),
        sa.Column("review_reason", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["task_id"], ["business_tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["submitted_by_id"], ["employees.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_id"], ["employees.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", "version", name="uq_task_submissions_task_version"),
        sa.UniqueConstraint(
            "task_id", "payload_hash", name="uq_task_submissions_task_payload"
        ),
    )
    op.create_index("ix_task_submissions_task_id", "task_submissions", ["task_id"])
    op.create_index(
        "ix_task_submissions_submitted_by_id", "task_submissions", ["submitted_by_id"]
    )
    op.create_index(
        "ix_task_submissions_reviewed_by_id", "task_submissions", ["reviewed_by_id"]
    )
    op.create_index(
        "ix_task_submissions_task_status", "task_submissions", ["task_id", "status"]
    )

    op.create_table(
        "task_executions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("submission_id", sa.Integer(), nullable=False),
        sa.Column("capability_name", sa.String(length=100), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING", "RUNNING", "SUCCEEDED", "FAILED",
                name="execution_status", native_enum=False, create_constraint=True,
            ),
            server_default="PENDING", nullable=False,
        ),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.CheckConstraint(
            "attempt_count >= 0", name="ck_task_executions_attempt_nonnegative"
        ),
        sa.ForeignKeyConstraint(["task_id"], ["business_tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["submission_id"], ["task_submissions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "task_id", "submission_id", "capability_name",
            name="uq_task_executions_task_submission_capability",
        ),
    )
    op.create_index("ix_task_executions_task_id", "task_executions", ["task_id"])
    op.create_index(
        "ix_task_executions_submission_id", "task_executions", ["submission_id"]
    )
    op.create_index(
        "ix_task_executions_idempotency_key", "task_executions",
        ["idempotency_key"], unique=True,
    )


def downgrade() -> None:
    op.drop_table("task_executions")
    op.drop_table("task_submissions")
    op.drop_table("task_recommendations")

    op.drop_constraint("task_status", "business_tasks", type_="check")
    op.execute(
        "UPDATE business_tasks SET status = CASE "
        "WHEN status = 'COMPLETED' THEN 'COMPLETED' "
        "WHEN status = 'CANCELLED' THEN 'CANCELLED' "
        "ELSE 'PENDING' END"
    )
    op.alter_column(
        "business_tasks",
        "status",
        existing_type=sa.String(length=22),
        type_=sa.String(length=9),
        server_default="PENDING",
    )
    op.create_check_constraint(
        "task_status", "business_tasks",
        "status IN ('PENDING', 'COMPLETED', 'CANCELLED')",
    )
