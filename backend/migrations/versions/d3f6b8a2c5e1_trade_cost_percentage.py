"""Record trade cost percentage_used.

Revision ID: d3f6b8a2c5e1
Revises: c8e1a4f7d2b9
Create Date: 2026-07-25 09:30:00.000000

Adds percentage_used to trade_costs (specification §5.2, §6.4). For costs entered as a
percentage of the trade total, freeze the EUR amount at creation and retain the
percentage for information and display.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "d3f6b8a2c5e1"
down_revision = "c8e1a4f7d2b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trade_costs", sa.Column("percentage_used", sa.Numeric(precision=8, scale=4), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("trade_costs", "percentage_used")
