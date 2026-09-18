"""create accounts receivable and payable

Revision ID: 20260918_02
Revises: 20260918_01
Create Date: 2026-09-18
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260918_02"
down_revision: str | Sequence[str] | None = "20260918_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "account_payables",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("reference_no", sa.String(length=64), nullable=False),
        sa.Column("supplier_name", sa.String(length=255), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column(
            "paid_amount",
            sa.Numeric(precision=18, scale=2),
            server_default="0",
            nullable=False,
        ),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "UNPAID",
                "PARTIALLY_PAID",
                "PAID",
                "OVERDUE",
                name="payable_status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="UNPAID",
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
        sa.CheckConstraint(
            "amount >= 0",
            name="ck_account_payables_amount_nonnegative",
        ),
        sa.CheckConstraint(
            "paid_amount >= 0",
            name="ck_account_payables_paid_amount_nonnegative",
        ),
        sa.CheckConstraint(
            "paid_amount <= amount",
            name="ck_account_payables_paid_not_above_amount",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_account_payables_reference_no",
        "account_payables",
        ["reference_no"],
        unique=True,
    )

    op.create_table(
        "account_receivables",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("sales_order_id", sa.Integer(), nullable=False),
        sa.Column("customer_name", sa.String(length=255), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column(
            "paid_amount",
            sa.Numeric(precision=18, scale=2),
            server_default="0",
            nullable=False,
        ),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "UNPAID",
                "PARTIALLY_PAID",
                "PAID",
                "OVERDUE",
                name="receivable_status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="UNPAID",
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
        sa.CheckConstraint(
            "amount >= 0",
            name="ck_account_receivables_amount_nonnegative",
        ),
        sa.CheckConstraint(
            "paid_amount >= 0",
            name="ck_account_receivables_paid_amount_nonnegative",
        ),
        sa.CheckConstraint(
            "paid_amount <= amount",
            name="ck_account_receivables_paid_not_above_amount",
        ),
        sa.ForeignKeyConstraint(["sales_order_id"], ["sales_orders.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_account_receivables_sales_order_id",
        "account_receivables",
        ["sales_order_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_account_receivables_sales_order_id",
        table_name="account_receivables",
    )
    op.drop_table("account_receivables")
    op.drop_index(
        "ix_account_payables_reference_no",
        table_name="account_payables",
    )
    op.drop_table("account_payables")
