"""Freeze source cash accounts for portfolio entities.

Revision ID: b8d1f4a7c2e9
Revises: a4c7e9b2d5f8
Create Date: 2026-08-27 10:00:00.000000

An investment account reference applies prospectively. Trades, income events, and costs
must remember where cash actually moved so later reference changes cannot reassign
historical cash flows.

Backfill uses only linked transactions as reliable evidence. Without a linked movement,
a legacy source remains NULL instead of inferring the current reference. Duplicate links
or links to investment accounts abort before schema changes.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "b8d1f4a7c2e9"
down_revision = "a4c7e9b2d5f8"
branch_labels = None
depends_on = None

SOURCES = (
    ("trades", "trade_id", "fk_trades_cash_account_id"),
    ("income_events", "income_event_id", "fk_income_events_cash_account_id"),
    ("portfolio_costs", "portfolio_cost_id", "fk_portfolio_costs_cash_account_id"),
)


def _count(connection: sa.Connection, query: str) -> int:
    return int(connection.scalar(sa.text(query)) or 0)


def _verify_linked_cashflows() -> None:
    connection = op.get_bind()
    problems: dict[str, int] = {}
    for table, link_column, _ in SOURCES:
        duplicates = _count(
            connection,
            f"""
            SELECT COUNT(*)
            FROM (
                SELECT {link_column}
                FROM transactions
                WHERE {link_column} IS NOT NULL
                GROUP BY {link_column}
                HAVING COUNT(*) > 1
            )
            """,
        )
        invalid_accounts = _count(
            connection,
            f"""
            SELECT COUNT(*)
            FROM transactions AS movement
            LEFT JOIN accounts AS cash ON cash.id = movement.account_id
            WHERE movement.{link_column} IS NOT NULL
              AND (cash.id IS NULL OR cash.type = 'investment')
            """,
        )
        if duplicates:
            problems[f"{table}: sources with multiple linked transactions"] = duplicates
        if invalid_accounts:
            problems[f"{table}: linked transactions without a valid cash account"] = (
                invalid_accounts
            )

    if problems:
        details = ", ".join(f"{name}: {count}" for name, count in problems.items())
        raise RuntimeError(
            "Source cash account migration aborted: existing data "
            f"requires an explicit decision ({details}). No data was changed."
        )


def upgrade() -> None:
    _verify_linked_cashflows()

    for table, _, foreign_key_name in SOURCES:
        with op.batch_alter_table(table, recreate="always") as batch:
            batch.add_column(sa.Column("cash_account_id", sa.Integer(), nullable=True))
            batch.create_foreign_key(
                foreign_key_name,
                "accounts",
                ["cash_account_id"],
                ["id"],
            )

    connection = op.get_bind()
    for table, link_column, _ in SOURCES:
        connection.execute(sa.text(f"""
                UPDATE {table}
                SET cash_account_id = (
                    SELECT movement.account_id
                    FROM transactions AS movement
                    WHERE movement.{link_column} = {table}.id
                )
                WHERE EXISTS (
                    SELECT 1
                    FROM transactions AS movement
                    WHERE movement.{link_column} = {table}.id
                )
                """))


def downgrade() -> None:
    for table, _, foreign_key_name in reversed(SOURCES):
        with op.batch_alter_table(table, recreate="always") as batch:
            batch.drop_constraint(foreign_key_name, type_="foreignkey")
            batch.drop_column("cash_account_id")
