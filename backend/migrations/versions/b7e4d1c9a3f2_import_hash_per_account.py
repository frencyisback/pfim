"""Include the destination account in import_hash.

Revision ID: b7e4d1c9a3f2
Revises: e1c7b3d9f0a2
Create Date: 2026-07-29 16:40:00.000000

transactions.import_hash identifies previously imported rows. Previously, date, amount,
and description alone formed a table-wide unique hash, causing an otherwise identical
movement on another account to be skipped. Equal same-day salary or rent payments on
different accounts are valid.

Hashes now include account_id through app.utils.deduplication.compute_row_hash.
Recalculate existing hashes from each stored row to keep future reimports from
duplicating those transactions.

Amount normalization uses canonical_amount at Numeric(18, 6) precision: CSV -1.5 and
database -1.500000 must produce the same hash.

Existing hashes are distinct under the UNIQUE constraint, so the original rows differ by
date, amount, or description; adding the account cannot make them identical.

Downgrade restores the format without accounts. If otherwise identical rows have since
been imported into different accounts, it stops and preserves them instead of violating
uniqueness.
"""

import sqlalchemy as sa
from alembic import op

from app.utils.deduplication import canonical_amount, compute_row_hash

# revision identifiers, used by Alembic.
revision = "b7e4d1c9a3f2"
down_revision = "e1c7b3d9f0a2"
branch_labels = None
depends_on = None


def _legacy_hash(date: str, amount, description: str | None) -> str:
    """Previous format: date, amount, and description without account.

    Defined here rather than imported so this migration preserves its historical contract
    even if compute_row_hash changes again.
    """
    import hashlib

    raw = f"{date}|{canonical_amount(amount)}|{description or ''}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _rows(conn):
    return conn.execute(
        sa.text(
            "SELECT id, account_id, date, amount, description FROM transactions "
            "WHERE import_hash IS NOT NULL"
        )
    ).fetchall()


def _rewrite(conn, rows, new_hash_of) -> None:
    for row in rows:
        conn.execute(
            sa.text("UPDATE transactions SET import_hash = :h WHERE id = :id"),
            {"h": new_hash_of(row), "id": row.id},
        )


def upgrade() -> None:
    conn = op.get_bind()
    rows = _rows(conn)
    _rewrite(
        conn,
        rows,
        lambda r: compute_row_hash(r.account_id, str(r.date)[:10], r.amount, r.description),
    )
    if rows:
        print(f"[b7e4d1c9a3f2] import_hash recalculated for {len(rows)} imported transactions.")


def downgrade() -> None:
    conn = op.get_bind()
    rows = _rows(conn)

    legacy_hashes = [_legacy_hash(str(r.date)[:10], r.amount, r.description) for r in rows]
    if len(set(legacy_hashes)) != len(legacy_hashes):
        raise RuntimeError(
            "Cannot downgrade: transactions imported into different accounts "
            "would share the same hash without the account. Removing it would violate "
            "import_hash uniqueness. Delete or reassign those rows before proceeding."
        )

    _rewrite(
        conn,
        rows,
        lambda r: _legacy_hash(str(r.date)[:10], r.amount, r.description),
    )
