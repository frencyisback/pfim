"""CSV import profiles.

Revision ID: f3a9c1d2e4b5
Revises: c6f36ee52efa
Create Date: 2026-07-23 10:00:00.000000

Creates csv_import_profiles (specification §8.1) for transaction CSV column mappings
managed in Settings. Starts empty so users can create their own profiles.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "f3a9c1d2e4b5"
down_revision = "c6f36ee52efa"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "csv_import_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("delimiter", sa.String(length=5), nullable=False),
        sa.Column("skip_rows", sa.Integer(), nullable=False),
        sa.Column("date_format", sa.String(length=30), nullable=False),
        sa.Column("date_column", sa.String(length=60), nullable=False),
        sa.Column("description_column", sa.String(length=60), nullable=False),
        sa.Column("amount_column", sa.String(length=60), nullable=False),
        sa.Column("category_column", sa.String(length=60), nullable=True),
        sa.Column("decimal_separator", sa.String(length=1), nullable=False),
        sa.Column("default_currency", sa.String(length=3), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )


def downgrade() -> None:
    op.drop_table("csv_import_profiles")
