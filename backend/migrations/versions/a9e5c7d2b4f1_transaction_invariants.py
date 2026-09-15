"""Enforce category and nonzero-amount transaction invariants.

Revision ID: a9e5c7d2b4f1
Revises: f6c4a2d8e1b9
Create Date: 2026-08-17 15:00:00.000000

Do not invent categories or correct amounts. Before changing the schema, validate every
historical row against the new rules. Incompatible data aborts the migration with
explicit counts so the owner can choose the correct values.

SQLite requires table reconstruction to change nullability and add CHECK constraints.
Batch mode copies compatible rows and recreates foreign keys, indexes, and existing
constraints.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "a9e5c7d2b4f1"
down_revision = "f6c4a2d8e1b9"
branch_labels = None
depends_on = None

CHECK_NAME = "ck_transactions_amount_nonzero"


def _count(connection: sa.Connection, query: str) -> int:
    return int(connection.scalar(sa.text(query)) or 0)


def _verify_existing_rows() -> None:
    connection = op.get_bind()
    problems = {
        "category_id NULL": _count(
            connection, "SELECT COUNT(*) FROM transactions WHERE category_id IS NULL"
        ),
        "amount zero": _count(connection, "SELECT COUNT(*) FROM transactions WHERE amount = 0"),
        "missing category": _count(
            connection,
            """
            SELECT COUNT(*)
            FROM transactions AS t
            LEFT JOIN categories AS c ON c.id = t.category_id
            WHERE t.category_id IS NOT NULL AND c.id IS NULL
            """,
        ),
        "non-leaf category": _count(
            connection,
            """
            SELECT COUNT(*)
            FROM transactions AS t
            WHERE EXISTS (
                SELECT 1 FROM categories AS child
                WHERE child.parent_id = t.category_id
            )
            """,
        ),
        "sign inconsistent with type": _count(
            connection,
            """
            SELECT COUNT(*)
            FROM transactions AS t
            JOIN categories AS c ON c.id = t.category_id
            WHERE (c.type = 'income' AND t.amount <= 0)
               OR (c.type = 'expense' AND t.amount >= 0)
               OR c.type NOT IN ('income', 'expense', 'transfer')
            """,
        ),
        "transfer outside the dedicated flow": _count(
            connection,
            """
            SELECT COUNT(*)
            FROM transactions AS t
            JOIN categories AS c ON c.id = t.category_id
            WHERE c.type = 'transfer' AND t.transfer_group_id IS NULL
            """,
        ),
    }
    found = {name: count for name, count in problems.items() if count}
    if found:
        details = ", ".join(f"{name}: {count}" for name, count in found.items())
        raise RuntimeError(
            "Transaction invariant migration aborted: existing data requires "
            f"an explicit correction ({details}). No backfill was performed."
        )


def upgrade() -> None:
    _verify_existing_rows()
    with op.batch_alter_table("transactions", recreate="always") as batch:
        batch.alter_column("category_id", existing_type=sa.Integer(), nullable=False)
        batch.create_check_constraint(CHECK_NAME, "amount <> 0")


def downgrade() -> None:
    with op.batch_alter_table("transactions", recreate="always") as batch:
        batch.drop_constraint(CHECK_NAME, type_="check")
        batch.alter_column("category_id", existing_type=sa.Integer(), nullable=True)
