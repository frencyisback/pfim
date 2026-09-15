"""Local account lifecycle constraints.

Revision ID: f2b6d8a4c1e9
Revises: e7b3c9a5d1f4
Create Date: 2026-08-25 19:00:00.000000

Do not invent references or zero balances. Before rebuilding accounts, validate local
incompatibilities and relations that SQLite CHECK constraints cannot express. Ambiguous
data leaves schema and rows unchanged.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "f2b6d8a4c1e9"
down_revision = "e7b3c9a5d1f4"
branch_labels = None
depends_on = None

INVESTMENT_CHECK = "ck_accounts_investment_cash_reference"
NONINVESTMENT_CHECK = "ck_accounts_noninvestment_no_reference"


def _count(connection: sa.Connection, query: str) -> int:
    return int(connection.scalar(sa.text(query)) or 0)


def _verify_existing_rows() -> None:
    connection = op.get_bind()
    problems = {
        "investment account with nonzero opening balance": _count(
            connection,
            "SELECT COUNT(*) FROM accounts " "WHERE type = 'investment' AND opening_balance <> 0",
        ),
        "investment account without reference": _count(
            connection,
            "SELECT COUNT(*) FROM accounts "
            "WHERE type = 'investment' AND reference_account_id IS NULL",
        ),
        "non-investment account with reference": _count(
            connection,
            "SELECT COUNT(*) FROM accounts "
            "WHERE type <> 'investment' AND reference_account_id IS NOT NULL",
        ),
        "reference does not exist": _count(
            connection,
            """
            SELECT COUNT(*)
            FROM accounts AS source
            LEFT JOIN accounts AS target ON target.id = source.reference_account_id
            WHERE source.reference_account_id IS NOT NULL AND target.id IS NULL
            """,
        ),
        "reference to another investment account": _count(
            connection,
            """
            SELECT COUNT(*)
            FROM accounts AS source
            JOIN accounts AS target ON target.id = source.reference_account_id
            WHERE source.type = 'investment' AND target.type = 'investment'
            """,
        ),
        "active investment account with inactive reference": _count(
            connection,
            """
            SELECT COUNT(*)
            FROM accounts AS source
            JOIN accounts AS target ON target.id = source.reference_account_id
            WHERE source.type = 'investment' AND source.is_active = 1
              AND target.is_active = 0
            """,
        ),
    }
    found = {name: count for name, count in problems.items() if count}
    if found:
        details = ", ".join(f"{name}: {count}" for name, count in found.items())
        raise RuntimeError(
            "Account lifecycle migration aborted: existing data requires "
            f"an explicit decision ({details}). No data was changed."
        )


def upgrade() -> None:
    _verify_existing_rows()
    with op.batch_alter_table("accounts", recreate="always") as batch:
        batch.create_check_constraint(
            INVESTMENT_CHECK,
            "type <> 'investment' OR " "(opening_balance = 0 AND reference_account_id IS NOT NULL)",
        )
        batch.create_check_constraint(
            NONINVESTMENT_CHECK,
            "type = 'investment' OR reference_account_id IS NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("accounts", recreate="always") as batch:
        batch.drop_constraint(NONINVESTMENT_CHECK, type_="check")
        batch.drop_constraint(INVESTMENT_CHECK, type_="check")
