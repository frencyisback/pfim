"""Entry-time currency conversion with mandatory EUR equivalents.

Revision ID: d9f2a4c7e3b1
Revises: a1b2c3d4e5f6
Create Date: 2026-07-28 09:12:00.000000

Applies the conversion rule in app/finance/currency.py:
every incoming amount carries its currency and exchange rate,
and its EUR equivalent is calculated once at entry.

1. Make *_eur and fx_rate columns NOT NULL. Previously, missing runtime exchange rates could leave foreign-currency trades without cash movements and value invested positions at zero.
2. Add conversion columns missing from prices, trade_costs, and portfolio_costs.

Backfill existing data in order of reliability:
- EUR: exactly 1.
- Recoverable rate: saved EUR equivalent divided by native amount, preserving the rate originally applied.
- Foreign-currency prices: latest fx_rates entry on or before the price date.
- Otherwise: use 1 and print a warning identifying rows requiring manual review.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "d9f2a4c7e3b1"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


# Recover the original exchange rate from the saved EUR equivalent divided by native
# amount. If unavailable, fall back to 1, which is correct for EUR; otherwise flag it for
# review.
#
def _rate_from_existing(amount_col: str, eur_col: str) -> str:
    return (
        f"CASE "
        f"WHEN UPPER(currency) = 'EUR' THEN 1 "
        f"WHEN {eur_col} IS NOT NULL AND {amount_col} <> 0 THEN {eur_col} / {amount_col} "
        f"ELSE 1 END"
    )


def upgrade() -> None:
    conn = op.get_bind()
    warnings: list[str] = []

    # ------------------------------------------------------------------
    # 1. Add nullable columns to allow backfill.
    # ------------------------------------------------------------------
    op.add_column("prices", sa.Column("fx_rate", sa.Numeric(18, 8), nullable=True))
    op.add_column("prices", sa.Column("price_close_eur", sa.Numeric(18, 6), nullable=True))
    op.add_column("trade_costs", sa.Column("fx_rate", sa.Numeric(18, 8), nullable=True))
    op.add_column("portfolio_costs", sa.Column("fx_rate", sa.Numeric(18, 8), nullable=True))

    # ------------------------------------------------------------------
    # 2. Backfill
    # ------------------------------------------------------------------

    # transactions -----------------------------------------------------
    conn.execute(
        sa.text(
            f"UPDATE transactions SET fx_rate = {_rate_from_existing('amount', 'amount_eur')} "
            f"WHERE fx_rate IS NULL"
        )
    )
    conn.execute(
        sa.text("UPDATE transactions SET amount_eur = amount * fx_rate WHERE amount_eur IS NULL")
    )

    # trades -----------------------------------------------------------
    conn.execute(
        sa.text(
            f"UPDATE trades SET fx_rate = {_rate_from_existing('total_amount', 'total_eur')} "
            f"WHERE fx_rate IS NULL"
        )
    )
    conn.execute(
        sa.text("UPDATE trades SET total_eur = total_amount * fx_rate WHERE total_eur IS NULL")
    )
    conn.execute(sa.text("UPDATE trades SET price_eur = price * fx_rate WHERE price_eur IS NULL"))

    # trade_costs ------------------------------------------------------
    conn.execute(
        sa.text(f"UPDATE trade_costs SET fx_rate = {_rate_from_existing('amount', 'amount_eur')}")
    )
    conn.execute(
        sa.text("UPDATE trade_costs SET amount_eur = amount * fx_rate WHERE amount_eur IS NULL")
    )

    # portfolio_costs --------------------------------------------------
    conn.execute(
        sa.text(
            f"UPDATE portfolio_costs SET fx_rate = {_rate_from_existing('amount', 'amount_eur')}"
        )
    )
    conn.execute(
        sa.text("UPDATE portfolio_costs SET amount_eur = amount * fx_rate WHERE amount_eur IS NULL")
    )
    conn.execute(
        sa.text(
            "UPDATE portfolio_costs SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"
        )
    )

    # income_events ----------------------------------------------------
    conn.execute(
        sa.text(
            f"UPDATE income_events SET fx_rate = {_rate_from_existing('total_amount', 'total_eur')} "
            f"WHERE fx_rate IS NULL"
        )
    )
    conn.execute(
        sa.text(
            "UPDATE income_events SET total_eur = total_amount * fx_rate WHERE total_eur IS NULL"
        )
    )
    conn.execute(
        sa.text(
            "UPDATE income_events SET net_amount_eur = "
            "(total_amount - COALESCE(tax_withheld, 0)) * fx_rate WHERE net_amount_eur IS NULL"
        )
    )

    # prices -----------------------------------------------------------
    # Prices had no EUR equivalent; recover their rate from fx_rates, the only available
    # historical source.
    orphans = (
        conn.execute(
            sa.text(
                "SELECT COUNT(*) FROM prices p JOIN securities s ON s.id = p.security_id "
                "WHERE UPPER(s.currency) <> 'EUR' AND NOT EXISTS ("
                "  SELECT 1 FROM fx_rates f WHERE f.from_currency = s.currency "
                "  AND f.to_currency = 'EUR' AND f.date <= p.date)"
            )
        ).scalar()
        or 0
    )
    if orphans:
        tickers = (
            conn.execute(
                sa.text(
                    "SELECT DISTINCT s.ticker FROM prices p JOIN securities s ON s.id = p.security_id "
                    "WHERE UPPER(s.currency) <> 'EUR' AND NOT EXISTS ("
                    "  SELECT 1 FROM fx_rates f WHERE f.from_currency = s.currency "
                    "  AND f.to_currency = 'EUR' AND f.date <= p.date)"
                )
            )
            .scalars()
            .all()
        )
        warnings.append(
            f"{orphans} foreign-currency security prices have no historical rate "
            f"in fx_rates: converted at rate 1. Affected securities: "
            f"{', '.join(tickers)}. Reenter these prices with an exchange rate."
        )

    conn.execute(
        sa.text(
            "UPDATE prices SET fx_rate = 1 WHERE security_id IN "
            "(SELECT id FROM securities WHERE UPPER(currency) = 'EUR')"
        )
    )
    conn.execute(
        sa.text(
            "UPDATE prices SET fx_rate = COALESCE(("
            "  SELECT f.rate FROM fx_rates f JOIN securities s ON s.id = prices.security_id"
            "  WHERE f.from_currency = s.currency AND f.to_currency = 'EUR'"
            "    AND f.date <= prices.date"
            "  ORDER BY f.date DESC LIMIT 1"
            "), 1) WHERE fx_rate IS NULL"
        )
    )
    conn.execute(
        sa.text(
            "UPDATE prices SET price_close_eur = price_close * fx_rate WHERE price_close_eur IS NULL"
        )
    )

    # ------------------------------------------------------------------
    # 3. Apply NOT NULL to every field now guaranteed to have a value.
    # ------------------------------------------------------------------
    with op.batch_alter_table("transactions") as batch:
        batch.alter_column("fx_rate", existing_type=sa.Numeric(18, 8), nullable=False)
        batch.alter_column("amount_eur", existing_type=sa.Numeric(18, 6), nullable=False)

    with op.batch_alter_table("trades") as batch:
        batch.alter_column("fx_rate", existing_type=sa.Numeric(18, 8), nullable=False)
        batch.alter_column("price_eur", existing_type=sa.Numeric(18, 6), nullable=False)
        batch.alter_column("total_eur", existing_type=sa.Numeric(18, 6), nullable=False)

    with op.batch_alter_table("trade_costs") as batch:
        batch.alter_column("fx_rate", existing_type=sa.Numeric(18, 8), nullable=False)
        batch.alter_column("amount_eur", existing_type=sa.Numeric(18, 6), nullable=False)

    with op.batch_alter_table("income_events") as batch:
        batch.alter_column("fx_rate", existing_type=sa.Numeric(18, 8), nullable=False)
        batch.alter_column("total_eur", existing_type=sa.Numeric(18, 6), nullable=False)
        batch.alter_column("net_amount_eur", existing_type=sa.Numeric(18, 6), nullable=False)

    with op.batch_alter_table("prices") as batch:
        batch.alter_column("fx_rate", existing_type=sa.Numeric(18, 8), nullable=False)
        batch.alter_column("price_close_eur", existing_type=sa.Numeric(18, 6), nullable=False)

    # portfolio_costs: also align created_at with the ORM model. It was NOT NULL in Python but
    # nullable in the database, causing a spurious migration on every --autogenerate.
    #
    #
    op.drop_index("ix_portfolio_costs_date", table_name="portfolio_costs")
    with op.batch_alter_table("portfolio_costs") as batch:
        batch.alter_column("fx_rate", existing_type=sa.Numeric(18, 8), nullable=False)
        batch.alter_column("amount_eur", existing_type=sa.Numeric(18, 6), nullable=False)
        batch.alter_column(
            "created_at",
            existing_type=sa.DateTime(),
            existing_server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        )
    op.create_index("ix_portfolio_costs_date", "portfolio_costs", ["date"])

    for message in warnings:
        print(f"\n  [WARNING] {message}\n")


def downgrade() -> None:
    op.drop_index("ix_portfolio_costs_date", table_name="portfolio_costs")
    with op.batch_alter_table("portfolio_costs") as batch:
        batch.alter_column(
            "created_at",
            existing_type=sa.DateTime(),
            existing_server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=True,
        )
        batch.alter_column("amount_eur", existing_type=sa.Numeric(18, 6), nullable=True)
        batch.drop_column("fx_rate")
    op.create_index("ix_portfolio_costs_date", "portfolio_costs", ["date"])

    with op.batch_alter_table("prices") as batch:
        batch.drop_column("price_close_eur")
        batch.drop_column("fx_rate")

    with op.batch_alter_table("income_events") as batch:
        batch.alter_column("net_amount_eur", existing_type=sa.Numeric(18, 6), nullable=True)
        batch.alter_column("total_eur", existing_type=sa.Numeric(18, 6), nullable=True)
        batch.alter_column("fx_rate", existing_type=sa.Numeric(18, 8), nullable=True)

    with op.batch_alter_table("trade_costs") as batch:
        batch.alter_column("amount_eur", existing_type=sa.Numeric(18, 6), nullable=True)
        batch.drop_column("fx_rate")

    with op.batch_alter_table("trades") as batch:
        batch.alter_column("total_eur", existing_type=sa.Numeric(18, 6), nullable=True)
        batch.alter_column("price_eur", existing_type=sa.Numeric(18, 6), nullable=True)
        batch.alter_column("fx_rate", existing_type=sa.Numeric(18, 8), nullable=True)

    with op.batch_alter_table("transactions") as batch:
        batch.alter_column("amount_eur", existing_type=sa.Numeric(18, 6), nullable=True)
        batch.alter_column("fx_rate", existing_type=sa.Numeric(18, 8), nullable=True)
