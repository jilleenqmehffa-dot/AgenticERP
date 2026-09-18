"""create initial schema

Revision ID: 20260918_01
Revises:
Create Date: 2026-09-18
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260918_01"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("sku", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=False),
        sa.Column("unit", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "ACTIVE",
                "INACTIVE",
                "DISCONTINUED",
                name="product_status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="ACTIVE",
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_products_sku", "products", ["sku"], unique=True)

    op.create_table(
        "sales_orders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("order_no", sa.String(length=64), nullable=False),
        sa.Column("customer_name", sa.String(length=255), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "DRAFT",
                "CONFIRMED",
                "PARTIALLY_FULFILLED",
                "FULFILLED",
                "CANCELLED",
                name="sales_order_status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="DRAFT",
            nullable=False,
        ),
        sa.Column("total_amount", sa.Numeric(precision=18, scale=2), nullable=False),
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
        sa.CheckConstraint(
            "total_amount >= 0",
            name="ck_sales_orders_total_amount_nonnegative",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_sales_orders_order_no",
        "sales_orders",
        ["order_no"],
        unique=True,
    )

    op.create_table(
        "inventories",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("warehouse_code", sa.String(length=64), nullable=False),
        sa.Column(
            "on_hand_quantity",
            sa.Numeric(precision=18, scale=3),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "reserved_quantity",
            sa.Numeric(precision=18, scale=3),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "NORMAL",
                "LOW_STOCK",
                "OUT_OF_STOCK",
                name="inventory_status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="OUT_OF_STOCK",
            nullable=False,
        ),
        sa.Column(
            "low_stock_threshold",
            sa.Numeric(precision=18, scale=3),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "low_stock_threshold >= 0",
            name="ck_inventories_low_stock_threshold_nonnegative",
        ),
        sa.CheckConstraint(
            "on_hand_quantity >= 0",
            name="ck_inventories_on_hand_quantity_nonnegative",
        ),
        sa.CheckConstraint(
            "reserved_quantity >= 0",
            name="ck_inventories_reserved_quantity_nonnegative",
        ),
        sa.CheckConstraint(
            "reserved_quantity <= on_hand_quantity",
            name="ck_inventories_reserved_not_above_on_hand",
        ),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "product_id",
            "warehouse_code",
            name="uq_inventories_product_warehouse",
        ),
    )
    op.create_index(
        "ix_inventories_product_id",
        "inventories",
        ["product_id"],
    )
    op.create_index(
        "ix_inventories_warehouse_code",
        "inventories",
        ["warehouse_code"],
    )

    op.create_table(
        "sales_order_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("sales_order_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=18, scale=3), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.CheckConstraint(
            "amount >= 0",
            name="ck_sales_order_items_amount_nonnegative",
        ),
        sa.CheckConstraint(
            "quantity > 0",
            name="ck_sales_order_items_quantity_positive",
        ),
        sa.CheckConstraint(
            "unit_price >= 0",
            name="ck_sales_order_items_unit_price_nonnegative",
        ),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.ForeignKeyConstraint(
            ["sales_order_id"],
            ["sales_orders.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_sales_order_items_product_id",
        "sales_order_items",
        ["product_id"],
    )
    op.create_index(
        "ix_sales_order_items_sales_order_id",
        "sales_order_items",
        ["sales_order_id"],
    )

    op.create_table(
        "stock_movements",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("warehouse_code", sa.String(length=64), nullable=False),
        sa.Column(
            "movement_type",
            sa.Enum(
                "IN",
                "OUT",
                name="movement_type",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("quantity", sa.Numeric(precision=18, scale=3), nullable=False),
        sa.Column("reference_type", sa.String(length=64), nullable=True),
        sa.Column("reference_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.CheckConstraint(
            "quantity > 0",
            name="ck_stock_movements_quantity_positive",
        ),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_stock_movements_product_id",
        "stock_movements",
        ["product_id"],
    )
    op.create_index(
        "ix_stock_movements_warehouse_code",
        "stock_movements",
        ["warehouse_code"],
    )
    op.create_index(
        "ix_stock_movements_reference",
        "stock_movements",
        ["reference_type", "reference_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_stock_movements_reference", table_name="stock_movements")
    op.drop_index("ix_stock_movements_warehouse_code", table_name="stock_movements")
    op.drop_index("ix_stock_movements_product_id", table_name="stock_movements")
    op.drop_table("stock_movements")
    op.drop_index("ix_sales_order_items_sales_order_id", table_name="sales_order_items")
    op.drop_index("ix_sales_order_items_product_id", table_name="sales_order_items")
    op.drop_table("sales_order_items")
    op.drop_index("ix_inventories_warehouse_code", table_name="inventories")
    op.drop_index("ix_inventories_product_id", table_name="inventories")
    op.drop_table("inventories")
    op.drop_index("ix_sales_orders_order_no", table_name="sales_orders")
    op.drop_table("sales_orders")
    op.drop_index("ix_products_sku", table_name="products")
    op.drop_table("products")
