"""add receiving disposition and putaway inventory flow

Revision ID: 20260927_14
Revises: 20260926_13
Create Date: 2026-09-27
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260927_14"
down_revision: str | Sequence[str] | None = "20260926_13"
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
    op.execute(
        "UPDATE inbound_receipts SET status = 'RECEIVING' "
        "WHERE status IN ('PENDING_INSPECTION', 'INSPECTING')"
    )
    op.drop_constraint("receipt_status", "inbound_receipts", type_="check")
    op.create_check_constraint(
        "receipt_status",
        "inbound_receipts",
        "status IN ('PENDING_RECEIPT', 'RECEIVING', 'INSPECTED', 'COMPLETED', 'CANCELLED')",
    )

    op.drop_constraint("stock_status", "inventory_buckets", type_="check")
    op.create_check_constraint(
        "stock_status",
        "inventory_buckets",
        "stock_status IN ('PENDING_PUTAWAY', 'AVAILABLE', 'RESERVED', 'PICKING', "
        "'FROZEN', 'QUARANTINED', 'DEFECTIVE')",
    )

    op.add_column(
        "warehouse_locations",
        sa.Column(
            "location_type",
            _enum(
                "warehouse_location_type",
                "RECEIVING",
                "STORAGE",
                "QUARANTINE",
                "SHIPPING",
            ),
            server_default="STORAGE",
            nullable=False,
        ),
    )
    op.add_column(
        "warehouse_locations",
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
    )

    op.add_column(
        "business_task_items",
        sa.Column("source_bucket_id", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "business_task_items",
        sa.Column(
            "target_stock_status",
            _enum(
                "business_task_target_stock_status",
                "PENDING_PUTAWAY",
                "AVAILABLE",
                "RESERVED",
                "PICKING",
                "FROZEN",
                "QUARANTINED",
                "DEFECTIVE",
            ),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_business_task_items_source_bucket_id_inventory_buckets",
        "business_task_items",
        "inventory_buckets",
        ["source_bucket_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_business_task_items_source_bucket_id",
        "business_task_items",
        ["source_bucket_id"],
    )

    op.create_table(
        "receipt_inspections",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("inbound_receipt_item_id", sa.BigInteger(), nullable=False),
        sa.Column("business_task_id", sa.BigInteger(), nullable=False),
        sa.Column("lot_no", sa.String(length=100), server_default="", nullable=False),
        sa.Column("received_quantity", sa.Numeric(18, 3), nullable=False),
        sa.Column("accepted_quantity", sa.Numeric(18, 3), nullable=False),
        sa.Column("defective_quantity", sa.Numeric(18, 3), nullable=False),
        sa.Column("quarantined_quantity", sa.Numeric(18, 3), nullable=False),
        sa.Column("rejected_quantity", sa.Numeric(18, 3), nullable=False),
        sa.Column("inspection_note", sa.Text(), nullable=True),
        sa.Column("inspected_by_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "inspected_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["inbound_receipt_item_id"],
            ["inbound_receipt_items.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["business_task_id"], ["business_tasks.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["inspected_by_id"], ["employees.id"], ondelete="RESTRICT"
        ),
        sa.CheckConstraint(
            "received_quantity > 0 AND accepted_quantity >= 0 "
            "AND defective_quantity >= 0 AND quarantined_quantity >= 0 "
            "AND rejected_quantity >= 0",
            name="ck_receipt_inspections_quantities_nonnegative",
        ),
        sa.CheckConstraint(
            "accepted_quantity + defective_quantity + quarantined_quantity "
            "+ rejected_quantity = received_quantity",
            name="ck_receipt_inspections_disposition_total",
        ),
        sa.UniqueConstraint("business_task_id"),
    )
    op.create_index(
        "ix_receipt_inspections_inbound_receipt_item_id",
        "receipt_inspections",
        ["inbound_receipt_item_id"],
    )
    op.create_index(
        "ix_receipt_inspections_inspected_by_id",
        "receipt_inspections",
        ["inspected_by_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_receipt_inspections_inspected_by_id", table_name="receipt_inspections")
    op.drop_index(
        "ix_receipt_inspections_inbound_receipt_item_id",
        table_name="receipt_inspections",
    )
    op.drop_table("receipt_inspections")
    op.drop_index(
        "ix_business_task_items_source_bucket_id", table_name="business_task_items"
    )
    op.drop_constraint(
        "fk_business_task_items_source_bucket_id_inventory_buckets",
        "business_task_items",
        type_="foreignkey",
    )
    op.drop_column("business_task_items", "target_stock_status")
    op.drop_column("business_task_items", "source_bucket_id")
    op.drop_column("warehouse_locations", "is_active")
    op.drop_column("warehouse_locations", "location_type")

    op.drop_constraint("stock_status", "inventory_buckets", type_="check")
    op.create_check_constraint(
        "stock_status",
        "inventory_buckets",
        "stock_status IN ('AVAILABLE', 'RESERVED', 'PICKING', 'FROZEN', "
        "'QUARANTINED', 'DEFECTIVE')",
    )
    op.drop_constraint("receipt_status", "inbound_receipts", type_="check")
    op.create_check_constraint(
        "receipt_status",
        "inbound_receipts",
        "status IN ('PENDING_RECEIPT', 'RECEIVING', 'PENDING_INSPECTION', "
        "'INSPECTING', 'INSPECTED', 'COMPLETED', 'CANCELLED')",
    )
