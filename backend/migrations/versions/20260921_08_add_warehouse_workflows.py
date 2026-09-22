"""add warehouse workflow models and remove partial states

Revision ID: 20260921_08
Revises: 20260919_07
Create Date: 2026-09-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260921_08"
down_revision: str | Sequence[str] | None = "20260919_07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _enum(name: str, *values: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=True)


def upgrade() -> None:
    _replace_existing_status_constraints()
    _extend_existing_models()
    _create_warehouse_headers()
    _create_warehouse_lines()


def _replace_existing_status_constraints() -> None:
    op.execute(
        "UPDATE sales_orders SET status = 'CONFIRMED' "
        "WHERE status = 'PARTIALLY_FULFILLED'"
    )
    op.drop_constraint("sales_order_status", "sales_orders", type_="check")
    op.create_check_constraint(
        "sales_order_status",
        "sales_orders",
        "status IN ('DRAFT', 'CONFIRMED', 'FULFILLED', 'CANCELLED')",
    )

    for table_name, constraint_name in (
        ("account_receivables", "receivable_status"),
        ("account_payables", "payable_status"),
    ):
        op.execute(
            f"UPDATE {table_name} SET status = 'UNPAID' "
            "WHERE status = 'PARTIALLY_PAID'"
        )
        op.drop_constraint(constraint_name, table_name, type_="check")
        op.create_check_constraint(
            constraint_name,
            table_name,
            "status IN ('UNPAID', 'PAID', 'OVERDUE')",
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
        "status IN ('PENDING', 'IN_PROGRESS', 'COMPLETED', 'FAILED', 'CANCELLED')",
    )


def _extend_existing_models() -> None:
    op.add_column(
        "sales_order_items",
        sa.Column("status", sa.String(length=9), server_default="PENDING", nullable=False),
    )
    op.create_check_constraint(
        "order_item_status",
        "sales_order_items",
        "status IN ('PENDING', 'FULFILLED', 'CANCELLED')",
    )
    for column_name in ("reserved_quantity", "picked_quantity", "shipped_quantity"):
        op.add_column(
            "sales_order_items",
            sa.Column(
                column_name,
                sa.Numeric(precision=18, scale=3),
                server_default="0",
                nullable=False,
            ),
        )
    op.create_check_constraint(
        "ck_sales_order_items_reserved_quantity_valid",
        "sales_order_items",
        "reserved_quantity >= 0 AND reserved_quantity <= quantity",
    )
    op.create_check_constraint(
        "ck_sales_order_items_picked_quantity_valid",
        "sales_order_items",
        "picked_quantity >= 0 AND picked_quantity <= reserved_quantity",
    )
    op.create_check_constraint(
        "ck_sales_order_items_shipped_quantity_valid",
        "sales_order_items",
        "shipped_quantity >= 0 AND shipped_quantity <= picked_quantity",
    )
    op.add_column(
        "business_tasks",
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "business_tasks",
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
    )


def _create_warehouse_headers() -> None:
    op.create_table(
        "outbound_orders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("outbound_no", sa.String(64), nullable=False),
        sa.Column("source_type", sa.String(64), nullable=True),
        sa.Column("source_id", sa.BigInteger(), nullable=True),
        sa.Column("warehouse_code", sa.String(64), nullable=False),
        sa.Column(
            "status",
            _enum(
                "outbound_status",
                "PENDING_OUTBOUND",
                "RESERVED",
                "PICKING",
                "READY_TO_SHIP",
                "SHIPPED",
                "COMPLETED",
                "CANCELLED",
            ),
            server_default="PENDING_OUTBOUND",
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("reserved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("picking_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ready_to_ship_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("shipped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "(source_type IS NULL) = (source_id IS NULL)",
            name="ck_outbound_orders_source_complete",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_outbound_orders_outbound_no", "outbound_orders", ["outbound_no"], unique=True)
    op.create_index("ix_outbound_orders_warehouse_code", "outbound_orders", ["warehouse_code"])
    op.create_index("ix_outbound_orders_source", "outbound_orders", ["source_type", "source_id"])

    op.create_table(
        "purchase_orders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("purchase_no", sa.String(64), nullable=False),
        sa.Column("supplier_name", sa.String(255), nullable=False),
        sa.Column(
            "status",
            _enum("purchase_order_status", "DRAFT", "ORDERED", "IN_TRANSIT", "RECEIVED", "CANCELLED"),
            server_default="DRAFT",
            nullable=False,
        ),
        sa.Column("ordered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("shipped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expected_arrival_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_purchase_orders_purchase_no", "purchase_orders", ["purchase_no"], unique=True)
    op.create_index("ix_purchase_orders_supplier_name", "purchase_orders", ["supplier_name"])

    op.create_table(
        "inbound_receipts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("receipt_no", sa.String(64), nullable=False),
        sa.Column("source_type", sa.String(64), nullable=True),
        sa.Column("source_id", sa.BigInteger(), nullable=True),
        sa.Column("warehouse_code", sa.String(64), nullable=False),
        sa.Column(
            "status",
            _enum(
                "receipt_status",
                "PENDING_RECEIPT",
                "RECEIVING",
                "PENDING_INSPECTION",
                "INSPECTING",
                "INSPECTED",
                "COMPLETED",
                "CANCELLED",
            ),
            server_default="PENDING_RECEIPT",
            nullable=False,
        ),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("inspection_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("inspected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "(source_type IS NULL) = (source_id IS NULL)",
            name="ck_inbound_receipts_source_complete",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_inbound_receipts_receipt_no", "inbound_receipts", ["receipt_no"], unique=True)
    op.create_index("ix_inbound_receipts_warehouse_code", "inbound_receipts", ["warehouse_code"])
    op.create_index("ix_inbound_receipts_source", "inbound_receipts", ["source_type", "source_id"])

    op.create_table(
        "return_orders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("return_no", sa.String(64), nullable=False),
        sa.Column(
            "direction",
            _enum("return_direction", "FROM_CUSTOMER", "TO_SUPPLIER"),
            nullable=False,
        ),
        sa.Column("source_type", sa.String(64), nullable=True),
        sa.Column("source_id", sa.BigInteger(), nullable=True),
        sa.Column("warehouse_code", sa.String(64), nullable=False),
        sa.Column(
            "status",
            _enum(
                "return_status",
                "REQUESTED",
                "APPROVED",
                "PENDING_OUTBOUND",
                "IN_TRANSIT",
                "PENDING_RECEIPT",
                "PENDING_INSPECTION",
                "RECEIVED",
                "COMPLETED",
                "REJECTED",
                "CANCELLED",
            ),
            server_default="REQUESTED",
            nullable=False,
        ),
        sa.Column("shipped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "(source_type IS NULL) = (source_id IS NULL)",
            name="ck_return_orders_source_complete",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_return_orders_return_no", "return_orders", ["return_no"], unique=True)
    op.create_index("ix_return_orders_warehouse_code", "return_orders", ["warehouse_code"])
    op.create_index("ix_return_orders_source", "return_orders", ["source_type", "source_id"])

    op.create_table(
        "stock_transfers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("transfer_no", sa.String(64), nullable=False),
        sa.Column("source_warehouse_code", sa.String(64), nullable=False),
        sa.Column("destination_warehouse_code", sa.String(64), nullable=False),
        sa.Column(
            "status",
            _enum(
                "transfer_status",
                "DRAFT",
                "PENDING_OUTBOUND",
                "PICKING",
                "IN_TRANSIT",
                "PENDING_RECEIPT",
                "RECEIVED",
                "COMPLETED",
                "CANCELLED",
            ),
            server_default="DRAFT",
            nullable=False,
        ),
        sa.Column("shipped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "source_warehouse_code <> destination_warehouse_code",
            name="ck_stock_transfers_warehouses_different",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_stock_transfers_transfer_no", "stock_transfers", ["transfer_no"], unique=True)
    op.create_index("ix_stock_transfers_source_warehouse_code", "stock_transfers", ["source_warehouse_code"])
    op.create_index("ix_stock_transfers_destination_warehouse_code", "stock_transfers", ["destination_warehouse_code"])

    op.create_table(
        "inventory_buckets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("warehouse_code", sa.String(64), nullable=False),
        sa.Column("location_code", sa.String(64), server_default="", nullable=False),
        sa.Column("lot_no", sa.String(100), server_default="", nullable=False),
        sa.Column(
            "stock_status",
            _enum("stock_status", "AVAILABLE", "RESERVED", "PICKING", "FROZEN", "QUARANTINED", "DEFECTIVE"),
            nullable=False,
        ),
        sa.Column("quantity", sa.Numeric(18, 3), server_default="0", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("quantity >= 0", name="ck_inventory_buckets_quantity_nonnegative"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "product_id",
            "warehouse_code",
            "location_code",
            "lot_no",
            "stock_status",
            name="uq_inventory_buckets_identity",
        ),
    )
    op.create_index("ix_inventory_buckets_product_id", "inventory_buckets", ["product_id"])
    op.create_index("ix_inventory_buckets_warehouse_code", "inventory_buckets", ["warehouse_code"])


def _create_warehouse_lines() -> None:
    op.create_table(
        "outbound_order_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("outbound_order_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("requested_quantity", sa.Numeric(18, 3), nullable=False),
        sa.Column("reserved_quantity", sa.Numeric(18, 3), server_default="0", nullable=False),
        sa.Column("picked_quantity", sa.Numeric(18, 3), server_default="0", nullable=False),
        sa.Column("shipped_quantity", sa.Numeric(18, 3), server_default="0", nullable=False),
        sa.CheckConstraint("requested_quantity > 0", name="ck_outbound_items_requested_positive"),
        sa.CheckConstraint("reserved_quantity >= 0 AND reserved_quantity <= requested_quantity", name="ck_outbound_items_reserved_valid"),
        sa.CheckConstraint("picked_quantity >= 0 AND picked_quantity <= reserved_quantity", name="ck_outbound_items_picked_valid"),
        sa.CheckConstraint("shipped_quantity >= 0 AND shipped_quantity <= picked_quantity", name="ck_outbound_items_shipped_valid"),
        sa.ForeignKeyConstraint(["outbound_order_id"], ["outbound_orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_outbound_order_items_outbound_order_id", "outbound_order_items", ["outbound_order_id"])
    op.create_index("ix_outbound_order_items_product_id", "outbound_order_items", ["product_id"])

    op.create_table(
        "stock_reservations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("reservation_no", sa.String(64), nullable=False),
        sa.Column("outbound_order_item_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("warehouse_code", sa.String(64), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 3), nullable=False),
        sa.Column(
            "status",
            _enum("reservation_status", "ACTIVE", "CONSUMED", "RELEASED", "EXPIRED", "CANCELLED"),
            server_default="ACTIVE",
            nullable=False,
        ),
        sa.Column("reserved_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("quantity > 0", name="ck_stock_reservations_quantity_positive"),
        sa.ForeignKeyConstraint(["outbound_order_item_id"], ["outbound_order_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_stock_reservations_reservation_no", "stock_reservations", ["reservation_no"], unique=True)
    op.create_index("ix_stock_reservations_outbound_order_item_id", "stock_reservations", ["outbound_order_item_id"])
    op.create_index("ix_stock_reservations_product_id", "stock_reservations", ["product_id"])
    op.create_index("ix_stock_reservations_warehouse_code", "stock_reservations", ["warehouse_code"])

    _create_purchase_items()
    _create_receipt_items()
    _create_return_items()
    _create_transfer_items()


def _create_purchase_items() -> None:
    op.create_table(
        "purchase_order_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("purchase_order_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("ordered_quantity", sa.Numeric(18, 3), nullable=False),
        sa.Column("received_quantity", sa.Numeric(18, 3), server_default="0", nullable=False),
        sa.Column("accepted_quantity", sa.Numeric(18, 3), server_default="0", nullable=False),
        sa.Column("rejected_quantity", sa.Numeric(18, 3), server_default="0", nullable=False),
        sa.CheckConstraint("ordered_quantity > 0", name="ck_purchase_items_ordered_positive"),
        sa.CheckConstraint("received_quantity >= 0 AND received_quantity <= ordered_quantity", name="ck_purchase_items_received_valid"),
        sa.CheckConstraint("accepted_quantity >= 0 AND rejected_quantity >= 0", name="ck_purchase_items_disposition_nonnegative"),
        sa.CheckConstraint("accepted_quantity + rejected_quantity <= received_quantity", name="ck_purchase_items_disposition_within_received"),
        sa.ForeignKeyConstraint(["purchase_order_id"], ["purchase_orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_purchase_order_items_purchase_order_id", "purchase_order_items", ["purchase_order_id"])
    op.create_index("ix_purchase_order_items_product_id", "purchase_order_items", ["product_id"])


def _create_receipt_items() -> None:
    op.create_table(
        "inbound_receipt_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("inbound_receipt_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("expected_quantity", sa.Numeric(18, 3), nullable=False),
        sa.Column("received_quantity", sa.Numeric(18, 3), server_default="0", nullable=False),
        sa.Column("accepted_quantity", sa.Numeric(18, 3), server_default="0", nullable=False),
        sa.Column("defective_quantity", sa.Numeric(18, 3), server_default="0", nullable=False),
        sa.Column("quarantined_quantity", sa.Numeric(18, 3), server_default="0", nullable=False),
        sa.Column("rejected_quantity", sa.Numeric(18, 3), server_default="0", nullable=False),
        sa.CheckConstraint("expected_quantity > 0", name="ck_receipt_items_expected_positive"),
        sa.CheckConstraint("received_quantity >= 0 AND received_quantity <= expected_quantity", name="ck_receipt_items_received_valid"),
        sa.CheckConstraint("accepted_quantity >= 0 AND defective_quantity >= 0 AND quarantined_quantity >= 0 AND rejected_quantity >= 0", name="ck_receipt_items_disposition_nonnegative"),
        sa.CheckConstraint("accepted_quantity + defective_quantity + quarantined_quantity + rejected_quantity <= received_quantity", name="ck_receipt_items_disposition_within_received"),
        sa.ForeignKeyConstraint(["inbound_receipt_id"], ["inbound_receipts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_inbound_receipt_items_inbound_receipt_id", "inbound_receipt_items", ["inbound_receipt_id"])
    op.create_index("ix_inbound_receipt_items_product_id", "inbound_receipt_items", ["product_id"])


def _create_return_items() -> None:
    op.create_table(
        "return_order_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("return_order_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("requested_quantity", sa.Numeric(18, 3), nullable=False),
        sa.Column("shipped_quantity", sa.Numeric(18, 3), server_default="0", nullable=False),
        sa.Column("received_quantity", sa.Numeric(18, 3), server_default="0", nullable=False),
        sa.CheckConstraint("requested_quantity > 0", name="ck_return_items_requested_positive"),
        sa.CheckConstraint("shipped_quantity >= 0 AND shipped_quantity <= requested_quantity", name="ck_return_items_shipped_valid"),
        sa.CheckConstraint("received_quantity >= 0 AND received_quantity <= shipped_quantity", name="ck_return_items_received_valid"),
        sa.ForeignKeyConstraint(["return_order_id"], ["return_orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_return_order_items_return_order_id", "return_order_items", ["return_order_id"])
    op.create_index("ix_return_order_items_product_id", "return_order_items", ["product_id"])


def _create_transfer_items() -> None:
    op.create_table(
        "stock_transfer_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("stock_transfer_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("planned_quantity", sa.Numeric(18, 3), nullable=False),
        sa.Column("shipped_quantity", sa.Numeric(18, 3), server_default="0", nullable=False),
        sa.Column("received_quantity", sa.Numeric(18, 3), server_default="0", nullable=False),
        sa.CheckConstraint("planned_quantity > 0", name="ck_transfer_items_planned_positive"),
        sa.CheckConstraint("shipped_quantity >= 0 AND shipped_quantity <= planned_quantity", name="ck_transfer_items_shipped_valid"),
        sa.CheckConstraint("received_quantity >= 0 AND received_quantity <= shipped_quantity", name="ck_transfer_items_received_valid"),
        sa.ForeignKeyConstraint(["stock_transfer_id"], ["stock_transfers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_stock_transfer_items_stock_transfer_id", "stock_transfer_items", ["stock_transfer_id"])
    op.create_index("ix_stock_transfer_items_product_id", "stock_transfer_items", ["product_id"])


def downgrade() -> None:
    for table_name in (
        "stock_reservations",
        "stock_transfer_items",
        "return_order_items",
        "inbound_receipt_items",
        "purchase_order_items",
        "outbound_order_items",
        "inventory_buckets",
        "stock_transfers",
        "return_orders",
        "inbound_receipts",
        "purchase_orders",
        "outbound_orders",
    ):
        op.drop_table(table_name)

    op.drop_column("business_tasks", "failed_at")
    op.drop_column("business_tasks", "started_at")
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

    for constraint_name in (
        "ck_sales_order_items_shipped_quantity_valid",
        "ck_sales_order_items_picked_quantity_valid",
        "ck_sales_order_items_reserved_quantity_valid",
        "order_item_status",
    ):
        op.drop_constraint(constraint_name, "sales_order_items", type_="check")
    for column_name in ("shipped_quantity", "picked_quantity", "reserved_quantity", "status"):
        op.drop_column("sales_order_items", column_name)

    op.drop_constraint("sales_order_status", "sales_orders", type_="check")
    op.create_check_constraint(
        "sales_order_status",
        "sales_orders",
        "status IN ('DRAFT', 'CONFIRMED', 'PARTIALLY_FULFILLED', 'FULFILLED', 'CANCELLED')",
    )
    for table_name, constraint_name in (
        ("account_receivables", "receivable_status"),
        ("account_payables", "payable_status"),
    ):
        op.drop_constraint(constraint_name, table_name, type_="check")
        op.create_check_constraint(
            constraint_name,
            table_name,
            "status IN ('UNPAID', 'PARTIALLY_PAID', 'PAID', 'OVERDUE')",
        )
