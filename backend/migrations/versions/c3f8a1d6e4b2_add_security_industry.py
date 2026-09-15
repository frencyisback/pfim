"""Add industry classification to securities.

Revision ID: c3f8a1d6e4b2
Revises: b8d1f4a7c2e9
Create Date: 2026-08-29 00:00:00.000000

Sector and country already exist. Industry completes the scalar classification required
by reports without introducing weighted exposures or an ETF-specific taxonomy.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "c3f8a1d6e4b2"
down_revision = "b8d1f4a7c2e9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("securities") as batch:
        batch.add_column(sa.Column("industry", sa.String(length=120), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("securities") as batch:
        batch.drop_column("industry")
