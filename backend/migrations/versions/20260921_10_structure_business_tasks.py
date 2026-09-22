"""structure business tasks and task items

Revision ID: 20260921_10
Revises: 20260921_09
Create Date: 2026-09-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260921_10"
down_revision: str | Sequence[str] | None = "20260921_09"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _create_warehouse_master_data()
    _extend_task_type()
    _reshape_business_tasks()
    _create_task_item_tables()
    _migrate_legacy_task_data()
    _drop_legacy_task_columns()


def _create_warehouse_master_data() -> None:
    op.create_table(
        "warehouses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
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
    op.create_index("ix_warehouses_code", "warehouses", ["code"], unique=True)

    op.create_table(
        "warehouse_locations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("warehouse_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ["warehouse_id"], ["warehouses.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "warehouse_id",
            "code",
            name="uq_warehouse_locations_warehouse_code",
        ),
    )
    op.create_index(
        "ix_warehouse_locations_warehouse_id",
        "warehouse_locations",
        ["warehouse_id"],
    )

    op.execute(
        """
        INSERT INTO warehouses (code, name)
        SELECT code, code
        FROM (
            SELECT warehouse_code AS code FROM inventories
            UNION SELECT warehouse_code FROM stock_movements
            UNION SELECT warehouse_code FROM inventory_buckets
            UNION SELECT warehouse_code FROM outbound_orders
            UNION SELECT warehouse_code FROM inbound_receipts
            UNION SELECT warehouse_code FROM return_orders
            UNION SELECT warehouse_code FROM stock_reservations
            UNION SELECT source_warehouse_code FROM stock_transfers
            UNION SELECT destination_warehouse_code FROM stock_transfers
            UNION SELECT planned_data ->> 'warehouse_code' FROM business_tasks
        ) AS warehouse_codes
        WHERE code IS NOT NULL AND btrim(code) <> ''
        ON CONFLICT (code) DO NOTHING
        """
    )


def _extend_task_type() -> None:
    op.drop_constraint("task_type", "business_tasks", type_="check")
    op.alter_column(
        "business_tasks",
        "task_type",
        existing_type=sa.String(length=9),
        type_=sa.String(length=15),
    )
    op.create_check_constraint(
        "task_type",
        "business_tasks",
        "task_type IN ("
        "'RECEIVE', 'PUTAWAY', 'PICK', 'PACK', "
        "'STOCK_IN', 'STOCK_OUT', 'TRANSFER', 'INVENTORY_COUNT'"
        ")",
    )


def _reshape_business_tasks() -> None:
    op.add_column(
        "business_tasks",
        sa.Column("warehouse_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_business_tasks_warehouse_id_warehouses",
        "business_tasks",
        "warehouses",
        ["warehouse_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_business_tasks_warehouse_id",
        "business_tasks",
        ["warehouse_id"],
    )
    op.add_column("business_tasks", sa.Column("reason", sa.Text(), nullable=True))
    op.execute(
        """
        UPDATE business_tasks AS task
        SET warehouse_id = warehouse.id,
            reason = NULLIF(
                concat_ws(E'\n', task.exception_reason, task.cancel_reason),
                ''
            )
        FROM warehouses AS warehouse
        WHERE warehouse.code = task.planned_data ->> 'warehouse_code'
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM business_tasks WHERE warehouse_id IS NULL
            ) THEN
                RAISE EXCEPTION
                    'business_tasks contains rows without a valid warehouse_code';
            END IF;
        END;
        $$
        """
    )
    op.alter_column(
        "business_tasks",
        "warehouse_id",
        existing_type=sa.Integer(),
        nullable=False,
    )

    op.drop_index(
        "ix_business_tasks_assigned_employee_id", table_name="business_tasks"
    )
    op.alter_column(
        "business_tasks",
        "assigned_employee_id",
        new_column_name="assignee_id",
        existing_type=sa.Integer(),
        existing_nullable=False,
    )
    op.create_index(
        "ix_business_tasks_assignee_id",
        "business_tasks",
        ["assignee_id"],
    )


def _create_task_item_tables() -> None:
    op.create_table(
        "business_task_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("from_location_id", sa.Integer(), nullable=True),
        sa.Column("to_location_id", sa.Integer(), nullable=True),
        sa.Column(
            "planned_quantity", sa.Numeric(precision=18, scale=3), nullable=False
        ),
        sa.Column(
            "actual_quantity", sa.Numeric(precision=18, scale=3), nullable=True
        ),
        sa.CheckConstraint(
            "actual_quantity IS NULL OR actual_quantity >= 0",
            name="ck_business_task_items_actual_quantity_nonnegative",
        ),
        sa.CheckConstraint(
            "planned_quantity > 0",
            name="ck_business_task_items_planned_quantity_positive",
        ),
        sa.ForeignKeyConstraint(
            ["from_location_id"],
            ["warehouse_locations.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.ForeignKeyConstraint(
            ["task_id"], ["business_tasks.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["to_location_id"],
            ["warehouse_locations.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_business_task_items_task_id", "business_task_items", ["task_id"]
    )
    op.create_index(
        "ix_business_task_items_product_id", "business_task_items", ["product_id"]
    )
    op.create_index(
        "ix_business_task_items_from_location_id",
        "business_task_items",
        ["from_location_id"],
    )
    op.create_index(
        "ix_business_task_items_to_location_id",
        "business_task_items",
        ["to_location_id"],
    )

    op.create_table(
        "inventory_count_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("location_id", sa.Integer(), nullable=False),
        sa.Column(
            "system_quantity", sa.Numeric(precision=18, scale=3), nullable=False
        ),
        sa.Column(
            "counted_quantity", sa.Numeric(precision=18, scale=3), nullable=True
        ),
        sa.Column(
            "difference_quantity",
            sa.Numeric(precision=18, scale=3),
            sa.Computed("counted_quantity - system_quantity", persisted=True),
            nullable=True,
        ),
        sa.CheckConstraint(
            "counted_quantity IS NULL OR counted_quantity >= 0",
            name="ck_inventory_count_items_counted_quantity_nonnegative",
        ),
        sa.CheckConstraint(
            "system_quantity >= 0",
            name="ck_inventory_count_items_system_quantity_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["location_id"],
            ["warehouse_locations.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.ForeignKeyConstraint(
            ["task_id"], ["business_tasks.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_inventory_count_items_task_id", "inventory_count_items", ["task_id"]
    )
    op.create_index(
        "ix_inventory_count_items_product_id",
        "inventory_count_items",
        ["product_id"],
    )
    op.create_index(
        "ix_inventory_count_items_location_id",
        "inventory_count_items",
        ["location_id"],
    )


def _migrate_legacy_task_data() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM business_tasks
                WHERE task_type IN ('STOCK_IN', 'STOCK_OUT')
                  AND (
                      planned_data ->> 'product_id' IS NULL
                      OR planned_data ->> 'quantity' IS NULL
                      OR NOT (planned_data ->> 'product_id' ~ '^[1-9][0-9]*$')
                      OR NOT (planned_data ->> 'quantity' ~ '^[0-9]+([.][0-9]+)?$')
                      OR (planned_data ->> 'quantity')::numeric <= 0
                  )
            ) THEN
                RAISE EXCEPTION
                    'business_tasks contains legacy rows that cannot be converted';
            END IF;
        END;
        $$
        """
    )
    op.execute(
        """
        INSERT INTO business_task_items (
            task_id,
            product_id,
            planned_quantity,
            actual_quantity
        )
        SELECT
            id,
            (planned_data ->> 'product_id')::integer,
            (planned_data ->> 'quantity')::numeric,
            CASE
                WHEN actual_data ->> 'quantity' IS NULL THEN NULL
                ELSE (actual_data ->> 'quantity')::numeric
            END
        FROM business_tasks
        WHERE task_type IN ('STOCK_IN', 'STOCK_OUT')
        """
    )


def _drop_legacy_task_columns() -> None:
    op.drop_column("business_tasks", "planned_data")
    op.drop_column("business_tasks", "actual_data")
    op.drop_column("business_tasks", "exception_reason")
    op.drop_column("business_tasks", "cancel_reason")


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM business_tasks
                WHERE task_type NOT IN ('STOCK_IN', 'STOCK_OUT')
            ) OR EXISTS (
                SELECT task_id
                FROM business_task_items
                GROUP BY task_id
                HAVING count(*) <> 1
            ) OR EXISTS (
                SELECT 1 FROM inventory_count_items
            ) THEN
                RAISE EXCEPTION
                    'business task data cannot be represented by the legacy schema';
            END IF;
        END;
        $$
        """
    )

    op.add_column(
        "business_tasks",
        sa.Column("planned_data", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "business_tasks",
        sa.Column("actual_data", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "business_tasks", sa.Column("exception_reason", sa.Text(), nullable=True)
    )
    op.add_column(
        "business_tasks", sa.Column("cancel_reason", sa.Text(), nullable=True)
    )
    op.execute(
        """
        UPDATE business_tasks AS task
        SET planned_data = jsonb_build_object(
                'product_id', item.product_id,
                'warehouse_code', warehouse.code,
                'quantity', item.planned_quantity
            ),
            actual_data = CASE
                WHEN item.actual_quantity IS NULL THEN NULL
                ELSE jsonb_build_object('quantity', item.actual_quantity)
            END,
            exception_reason = CASE
                WHEN task.status = 'COMPLETED' THEN task.reason
                ELSE NULL
            END,
            cancel_reason = CASE
                WHEN task.status = 'CANCELLED' THEN task.reason
                ELSE NULL
            END
        FROM business_task_items AS item, warehouses AS warehouse
        WHERE item.task_id = task.id
          AND warehouse.id = task.warehouse_id
        """
    )
    op.alter_column(
        "business_tasks",
        "planned_data",
        existing_type=postgresql.JSONB(),
        nullable=False,
    )

    op.drop_table("inventory_count_items")
    op.drop_table("business_task_items")

    op.drop_index("ix_business_tasks_assignee_id", table_name="business_tasks")
    op.alter_column(
        "business_tasks",
        "assignee_id",
        new_column_name="assigned_employee_id",
        existing_type=sa.Integer(),
        existing_nullable=False,
    )
    op.create_index(
        "ix_business_tasks_assigned_employee_id",
        "business_tasks",
        ["assigned_employee_id"],
    )
    op.drop_index("ix_business_tasks_warehouse_id", table_name="business_tasks")
    op.drop_constraint(
        "fk_business_tasks_warehouse_id_warehouses",
        "business_tasks",
        type_="foreignkey",
    )
    op.drop_column("business_tasks", "warehouse_id")
    op.drop_column("business_tasks", "reason")

    op.drop_table("warehouse_locations")
    op.drop_table("warehouses")

    op.drop_constraint("task_type", "business_tasks", type_="check")
    op.alter_column(
        "business_tasks",
        "task_type",
        existing_type=sa.String(length=15),
        type_=sa.String(length=9),
    )
    op.create_check_constraint(
        "task_type",
        "business_tasks",
        "task_type IN ('STOCK_IN', 'STOCK_OUT')",
    )
