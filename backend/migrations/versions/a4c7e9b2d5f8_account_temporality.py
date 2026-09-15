"""Account opening and closing dates.

Revision ID: a4c7e9b2d5f8
Revises: f2b6d8a4c1e9
Create Date: 2026-08-26 19:00:00.000000

Dates are intentionally nullable. Legacy accounts have no reliable source for opening
and closing dates, so both remain NULL to mean unknown and preserve historical
snapshots. This migration does not update or delete existing rows.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "a4c7e9b2d5f8"
down_revision = "f2b6d8a4c1e9"
branch_labels = None
depends_on = None

LIFECYCLE_DATES_CHECK = "ck_accounts_lifecycle_dates"


def upgrade() -> None:
    with op.batch_alter_table("accounts", recreate="always") as batch:
        batch.add_column(sa.Column("opened_on", sa.Date(), nullable=True))
        batch.add_column(sa.Column("closed_on", sa.Date(), nullable=True))
        batch.create_check_constraint(
            LIFECYCLE_DATES_CHECK,
            "closed_on IS NULL OR opened_on IS NULL OR closed_on >= opened_on",
        )


def downgrade() -> None:
    with op.batch_alter_table("accounts", recreate="always") as batch:
        batch.drop_constraint(LIFECYCLE_DATES_CHECK, type_="check")
        batch.drop_column("closed_on")
        batch.drop_column("opened_on")
