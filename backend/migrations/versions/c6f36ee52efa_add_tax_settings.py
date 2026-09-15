"""Add tax settings.

Revision ID: c6f36ee52efa
Revises: 33d80081a422
Create Date: 2026-07-12 08:13:31.067235

Initialize the default tax rates from specification §11.3. Users can edit all rates
through the API and UI.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "c6f36ee52efa"
down_revision = "33d80081a422"
branch_labels = None
depends_on = None

tax_settings_table = sa.table(
    "tax_settings",
    sa.column("key", sa.String),
    sa.column("value", sa.Numeric),
    sa.column("description", sa.Text),
)

DEFAULT_TAX_SETTINGS = [
    {
        "key": "capital_gains_tax_rate",
        "value": 26.00,
        "description": "Substitute tax on capital gains",
    },
    {
        "key": "dividend_withholding_it",
        "value": 26.00,
        "description": "Withholding tax on Italian security dividends",
    },
    {
        "key": "dividend_withholding_us",
        "value": 15.00,
        "description": "Withholding tax on US security dividends (WHT)",
    },
    {
        "key": "stamp_duty_rate",
        "value": 0.20,
        "description": "Stamp duty on securities",
    },
]


def upgrade() -> None:
    op.create_table(
        "tax_settings",
        sa.Column("key", sa.String(length=60), nullable=False),
        sa.Column("value", sa.Numeric(precision=8, scale=4), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("key"),
    )
    op.bulk_insert(tax_settings_table, DEFAULT_TAX_SETTINGS)


def downgrade() -> None:
    op.drop_table("tax_settings")
