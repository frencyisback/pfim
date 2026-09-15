"""Portfolio costs and linked cash transactions.

Revision ID: a1b2c3d4e5f6
Revises: e5a9c3f1b7d4
Create Date: 2026-07-26 12:00:00.000000

Recurring portfolio costs (specification §11.5): stamp duty, custody, and account fees.
Unlike trade_costs, these apply to the portfolio as a whole.

Like trades and income events, each cost generates a linked cash transaction on the
reference account (§5.2), using transactions.portfolio_cost_id.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = "e5a9c3f1b7d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "portfolio_costs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("cost_type", sa.String(length=30), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("amount", sa.Numeric(18, 6), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="EUR"),
        sa.Column("amount_eur", sa.Numeric(18, 6), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_portfolio_costs_date", "portfolio_costs", ["date"])

    # SQLite requires batch_alter_table for ADD CONSTRAINT.
    with op.batch_alter_table("transactions") as batch_op:
        batch_op.add_column(sa.Column("portfolio_cost_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_transactions_portfolio_cost_id", "portfolio_costs", ["portfolio_cost_id"], ["id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("transactions") as batch_op:
        batch_op.drop_constraint("fk_transactions_portfolio_cost_id", type_="foreignkey")
        batch_op.drop_column("portfolio_cost_id")

    op.drop_index("ix_portfolio_costs_date", table_name="portfolio_costs")
    op.drop_table("portfolio_costs")
