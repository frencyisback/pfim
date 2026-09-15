"""Remove unused OHLCV price fields.

Revision ID: f6c4a2d8e1b9
Revises: b7e4d1c9a3f2
Create Date: 2026-08-17 12:00:00.000000

PFIM uses closing prices to value positions. The open, high, low, and volume fields do
not participate in calculations and unnecessarily complicate CSV and API formats.

SQLite versions differ in support for removing multiple columns. Batch mode rebuilds
prices once, copies retained columns, and recreates the foreign key and unique
constraint without deleting price rows.

Downgrade recreates nullable columns. Removed OHLCV values cannot be recovered and
remain NULL.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "f6c4a2d8e1b9"
down_revision = "b7e4d1c9a3f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # recreate="always" makes behavior deterministic even on SQLite versions with partial DROP
    # COLUMN support. Remove all four columns in one table reconstruction.
    #
    with op.batch_alter_table("prices", recreate="always") as batch:
        batch.drop_column("price_open")
        batch.drop_column("price_high")
        batch.drop_column("price_low")
        batch.drop_column("volume")


def downgrade() -> None:
    with op.batch_alter_table("prices", recreate="always") as batch:
        batch.add_column(sa.Column("price_open", sa.Numeric(18, 6), nullable=True))
        batch.add_column(sa.Column("price_high", sa.Numeric(18, 6), nullable=True))
        batch.add_column(sa.Column("price_low", sa.Numeric(18, 6), nullable=True))
        batch.add_column(sa.Column("volume", sa.BigInteger(), nullable=True))
