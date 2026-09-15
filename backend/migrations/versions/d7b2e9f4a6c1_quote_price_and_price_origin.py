"""Separate quoted prices and link trade-generated prices.

Revision ID: d7b2e9f4a6c1
Revises: c3f8a1d6e4b2
Create Date: 2026-08-30 00:00:00.000000

trades.price remains the settlement price. quote_price is the unit price in the security
currency, used by native FIFO.

It cannot be reconstructed for legacy trades with different settlement and security
currencies. Validate before any DDL and stop instead of inventing historical prices.

prices.origin_trade_id distinguishes trade-derived prices from manual/imported prices.
Preserve existing orphan source=trade prices as legacy_trade_orphan; deleting them is an
operational data decision rather than a schema migration.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "d7b2e9f4a6c1"
down_revision = "c3f8a1d6e4b2"
branch_labels = None
depends_on = None


def _require_unambiguous_legacy_trades(connection) -> None:
    mismatches = (
        connection.execute(
            sa.text(
                "SELECT t.id FROM trades t "
                "JOIN securities s ON s.id = t.security_id "
                "WHERE UPPER(TRIM(t.currency)) <> UPPER(TRIM(s.currency)) "
                "ORDER BY t.id"
            )
        )
        .scalars()
        .all()
    )
    if mismatches:
        preview = ", ".join(str(trade_id) for trade_id in mismatches[:20])
        suffix = "..." if len(mismatches) > 20 else ""
        raise RuntimeError(
            "Migration aborted: the quote-currency price cannot be "
            f"reconstructed for {len(mismatches)} legacy trades (IDs: {preview}{suffix}). "
            "Explicitly correct these records before retrying."
        )


def upgrade() -> None:
    connection = op.get_bind()
    _require_unambiguous_legacy_trades(connection)

    with op.batch_alter_table("trades") as batch:
        batch.add_column(sa.Column("quote_price", sa.Numeric(18, 6), nullable=True))
    connection.execute(sa.text("UPDATE trades SET quote_price = price"))
    with op.batch_alter_table("trades") as batch:
        batch.alter_column("quote_price", existing_type=sa.Numeric(18, 6), nullable=False)
        batch.create_check_constraint(
            "ck_trades_quote_price_positive",
            "quote_price >= 0.000001 AND quote_price <= 999999999999.999999",
        )

    with op.batch_alter_table("prices") as batch:
        batch.add_column(sa.Column("origin_trade_id", sa.Integer(), nullable=True))

    # An automatic price may remain after its trade was deleted. Link only a unique,
    # verifiable match. Identical same-day legacy trades are indistinguishable and remain
    # unlinked rather than being assigned arbitrarily.
    #
    connection.execute(
        sa.text(
            "UPDATE prices SET origin_trade_id = ("
            "  SELECT MIN(t.id) FROM trades t "
            "  WHERE t.security_id = prices.security_id "
            "    AND t.date = prices.date "
            "    AND t.quote_price = prices.price_close "
            "    AND t.price_eur = prices.price_close_eur"
            ") WHERE source = 'trade' AND 1 = ("
            "  SELECT COUNT(*) FROM trades t "
            "  WHERE t.security_id = prices.security_id "
            "    AND t.date = prices.date "
            "    AND t.quote_price = prices.price_close "
            "    AND t.price_eur = prices.price_close_eur"
            ")"
        )
    )
    connection.execute(
        sa.text(
            "UPDATE prices SET source = 'legacy_trade_orphan' "
            "WHERE source = 'trade' AND origin_trade_id IS NULL"
        )
    )

    with op.batch_alter_table("prices") as batch:
        batch.create_foreign_key(
            "fk_prices_origin_trade_id_trades",
            "trades",
            ["origin_trade_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.create_unique_constraint("uq_prices_origin_trade_id", ["origin_trade_id"])
        batch.create_check_constraint(
            "ck_prices_trade_origin_consistent",
            "(source = 'trade' AND origin_trade_id IS NOT NULL) OR "
            "(source <> 'trade' AND origin_trade_id IS NULL)",
        )


def downgrade() -> None:
    connection = op.get_bind()
    with op.batch_alter_table("prices") as batch:
        batch.drop_constraint("ck_prices_trade_origin_consistent", type_="check")
        batch.drop_constraint("uq_prices_origin_trade_id", type_="unique")
        batch.drop_constraint("fk_prices_origin_trade_id_trades", type_="foreignkey")
        batch.drop_column("origin_trade_id")
    connection.execute(
        sa.text("UPDATE prices SET source = 'trade' WHERE source = 'legacy_trade_orphan'")
    )

    with op.batch_alter_table("trades") as batch:
        batch.drop_constraint("ck_trades_quote_price_positive", type_="check")
        batch.drop_column("quote_price")
