"""Indexes on filter columns (specification §12.3).

Revision ID: e1c7b3d9f0a2
Revises: d9f2a4c7e3b1
Create Date: 2026-07-28 14:05:00.000000

Adds the required indexes beyond the implicit UNIQUE index on prices(security_id, date).
These columns filter account balances and transaction lists, period/category reports,
and security position calculations.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "e1c7b3d9f0a2"
down_revision = "d9f2a4c7e3b1"
branch_labels = None
depends_on = None

INDEXES = [
    ("ix_transactions_account_id", "transactions", ["account_id"]),
    ("ix_transactions_category_id", "transactions", ["category_id"]),
    ("ix_transactions_date", "transactions", ["date"]),
    ("ix_trades_security_id", "trades", ["security_id"]),
    ("ix_trades_account_id", "trades", ["account_id"]),
]


def upgrade() -> None:
    for name, table, columns in INDEXES:
        op.create_index(name, table, columns)


def downgrade() -> None:
    for name, table, _ in reversed(INDEXES):
        op.drop_index(name, table_name=table)
