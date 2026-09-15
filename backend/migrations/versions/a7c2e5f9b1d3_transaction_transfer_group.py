"""Transaction transfer groups.

Revision ID: a7c2e5f9b1d3
Revises: f3a9c1d2e4b5
Create Date: 2026-07-24 09:00:00.000000

Adds transfer_group_id to transactions (specification §5.1), linking the two sides of an
internal account transfer: negative at the source and positive at the destination.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "a7c2e5f9b1d3"
down_revision = "f3a9c1d2e4b5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "transactions", sa.Column("transfer_group_id", sa.String(length=36), nullable=True)
    )
    op.create_index("ix_transactions_transfer_group_id", "transactions", ["transfer_group_id"])


def downgrade() -> None:
    op.drop_index("ix_transactions_transfer_group_id", table_name="transactions")
    op.drop_column("transactions", "transfer_group_id")
