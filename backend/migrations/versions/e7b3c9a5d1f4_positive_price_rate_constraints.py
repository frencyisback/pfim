"""Require positive prices and exchange rates.

Revision ID: e7b3c9a5d1f4
Revises: d4e8f2a6c1b9
Create Date: 2026-08-17 19:30:00.000000

Before rebuilding SQLite tables, validate historical rows and abort with explicit counts
for null, nonpositive, or NaN values. Do not correct, delete, or reclassify data.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "e7b3c9a5d1f4"
down_revision = "d4e8f2a6c1b9"
branch_labels = None
depends_on = None

PRICE_CLOSE_CHECK = "ck_prices_price_close_positive"
PRICE_FX_CHECK = "ck_prices_fx_rate_positive"
PRICE_EUR_CHECK = "ck_prices_price_close_eur_positive"
FX_RATE_CHECK = "ck_fx_rates_rate_positive"


def _count(connection: sa.Connection, query: str) -> int:
    return int(connection.scalar(sa.text(query)) or 0)


def _verify_existing_rows() -> None:
    connection = op.get_bind()
    problems = {
        "prices.price_close nonpositive/nonfinite": _count(
            connection,
            "SELECT COUNT(*) FROM prices "
            "WHERE price_close IS NULL OR price_close < 0.000001 "
            "OR price_close > 999999999999.999999 OR price_close != price_close",
        ),
        "prices.fx_rate nonpositive/nonfinite": _count(
            connection,
            "SELECT COUNT(*) FROM prices "
            "WHERE fx_rate IS NULL OR fx_rate < 0.00000001 "
            "OR fx_rate > 9999999999.99999999 OR fx_rate != fx_rate",
        ),
        "prices.price_close_eur nonpositive/nonfinite": _count(
            connection,
            "SELECT COUNT(*) FROM prices WHERE price_close_eur IS NULL "
            "OR price_close_eur < 0.000001 OR price_close_eur > 999999999999.999999 "
            "OR price_close_eur != price_close_eur",
        ),
        "fx_rates.rate nonpositive/nonfinite": _count(
            connection,
            "SELECT COUNT(*) FROM fx_rates "
            "WHERE rate IS NULL OR rate < 0.00000001 "
            "OR rate > 9999999999.99999999 OR rate != rate",
        ),
    }
    found = {name: count for name, count in problems.items() if count}
    if found:
        details = ", ".join(f"{name}: {count}" for name, count in found.items())
        raise RuntimeError(
            "Price/exchange-rate constraint migration aborted: existing data requires "
            f"an explicit correction ({details}). No data was changed."
        )


def upgrade() -> None:
    _verify_existing_rows()
    with op.batch_alter_table("prices", recreate="always") as batch:
        batch.create_check_constraint(
            PRICE_CLOSE_CHECK,
            "price_close >= 0.000001 AND price_close <= 999999999999.999999",
        )
        batch.create_check_constraint(
            PRICE_FX_CHECK,
            "fx_rate >= 0.00000001 AND fx_rate <= 9999999999.99999999",
        )
        batch.create_check_constraint(
            PRICE_EUR_CHECK,
            "price_close_eur >= 0.000001 AND price_close_eur <= 999999999999.999999",
        )
    with op.batch_alter_table("fx_rates", recreate="always") as batch:
        batch.create_check_constraint(
            FX_RATE_CHECK,
            "rate >= 0.00000001 AND rate <= 9999999999.99999999",
        )


def downgrade() -> None:
    with op.batch_alter_table("fx_rates", recreate="always") as batch:
        batch.drop_constraint(FX_RATE_CHECK, type_="check")
    with op.batch_alter_table("prices", recreate="always") as batch:
        batch.drop_constraint(PRICE_EUR_CHECK, type_="check")
        batch.drop_constraint(PRICE_FX_CHECK, type_="check")
        batch.drop_constraint(PRICE_CLOSE_CHECK, type_="check")
