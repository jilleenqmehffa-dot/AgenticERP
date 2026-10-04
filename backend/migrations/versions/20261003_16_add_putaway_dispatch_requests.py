"""add putaway dispatch requests

Revision ID: 20261003_16
Revises: 20260927_15
Create Date: 2026-10-03
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261003_16"
down_revision: str | Sequence[str] | None = "20260927_15"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _enum(name: str, *values: str) -> sa.Enum:
    return sa.Enum(
        *values,
        name=name,
        native_enum=False,
        create_constraint=True,
    )


def upgrade() -> None:
    op.create_table(
        "putaway_dispatch_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("inspection_id", sa.Integer(), nullable=False),
        sa.Column("source_bucket_id", sa.Integer(), nullable=False),
        sa.Column("warehouse_id", sa.Integer(), nullable=False),
        sa.Column("from_location_id", sa.Integer(), nullable=False),
        sa.Column(
            "required_location_type",
            _enum(
                "putaway_dispatch_location_type",
                "RECEIVING",
                "STORAGE",
                "QUARANTINE",
                "SHIPPING",
            ),
            nullable=False,
        ),
        sa.Column(
            "target_stock_status",
            _enum(
                "putaway_dispatch_target_stock_status",
                "PENDING_PUTAWAY",
                "AVAILABLE",
                "RESERVED",
                "PICKING",
                "FROZEN",
                "QUARANTINED",
                "DEFECTIVE",
            ),
            nullable=False,
        ),
        sa.Column("planned_quantity", sa.Numeric(18, 3), nullable=False),
        sa.Column("generation_key", sa.String(length=128), nullable=False),
        sa.Column(
            "status",
            _enum(
                "dispatch_request_status",
                "PENDING",
                "PUBLISHED",
                "CANCELLED",
            ),
            server_default="PENDING",
            nullable=False,
        ),
        sa.Column("published_task_id", sa.Integer(), nullable=True),
        sa.Column(
            "published_by_type",
            _enum(
                "putaway_dispatch_actor_type",
                "EMPLOYEE",
                "SYSTEM",
                "AGENT",
            ),
            nullable=True,
        ),
        sa.Column("published_by_id", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["inspection_id"],
            ["receipt_inspections.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_bucket_id"],
            ["inventory_buckets.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["warehouse_id"],
            ["warehouses.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["from_location_id"],
            ["warehouse_locations.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["published_task_id"],
            ["business_tasks.id"],
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "planned_quantity > 0",
            name="ck_putaway_dispatch_requests_quantity_positive",
        ),
        sa.CheckConstraint(
            "status != 'PUBLISHED' OR "
            "(published_task_id IS NOT NULL AND published_by_type IS NOT NULL "
            "AND published_by_id IS NOT NULL AND published_at IS NOT NULL)",
            name="ck_putaway_dispatch_requests_published_complete",
        ),
        sa.CheckConstraint(
            "status != 'PUBLISHED' OR published_by_type != 'SYSTEM'",
            name="ck_putaway_dispatch_requests_publisher_not_system",
        ),
        sa.UniqueConstraint(
            "generation_key",
            name="uq_putaway_dispatch_requests_generation_key",
        ),
        sa.UniqueConstraint(
            "published_task_id",
            name="uq_putaway_dispatch_requests_published_task",
        ),
    )
    for column_name in (
        "inspection_id",
        "source_bucket_id",
        "warehouse_id",
        "from_location_id",
    ):
        op.create_index(
            f"ix_putaway_dispatch_requests_{column_name}",
            "putaway_dispatch_requests",
            [column_name],
        )
    op.create_index(
        "ix_putaway_dispatch_requests_warehouse_status",
        "putaway_dispatch_requests",
        ["warehouse_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_putaway_dispatch_requests_warehouse_status",
        table_name="putaway_dispatch_requests",
    )
    for column_name in (
        "from_location_id",
        "warehouse_id",
        "source_bucket_id",
        "inspection_id",
    ):
        op.drop_index(
            f"ix_putaway_dispatch_requests_{column_name}",
            table_name="putaway_dispatch_requests",
        )
    op.drop_table("putaway_dispatch_requests")
