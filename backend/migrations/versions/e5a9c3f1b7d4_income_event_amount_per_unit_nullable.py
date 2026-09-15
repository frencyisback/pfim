"""Make income_event amount_per_unit nullable.

Revision ID: e5a9c3f1b7d4
Revises: d3f6b8a2c5e1
Create Date: 2026-07-25 10:00:00.000000

Simplifies coupon/dividend input (specification §5.2, §7.4.2): users enter total gross
income and withholding without a required amount_per_unit. The unit amount can still be
calculated when quantity_held is known.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "e5a9c3f1b7d4"
down_revision = "d3f6b8a2c5e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("income_events") as batch_op:
        batch_op.alter_column("amount_per_unit", existing_type=sa.Numeric(18, 6), nullable=True)


def downgrade() -> None:
    with op.batch_alter_table("income_events") as batch_op:
        batch_op.alter_column("amount_per_unit", existing_type=sa.Numeric(18, 6), nullable=False)
