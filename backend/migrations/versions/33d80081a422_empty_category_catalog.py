"""Keep the initial category catalog empty.

Revision ID: 33d80081a422
Revises: 21363943d743

Users create their own categories. Categories required by portfolio and
transfer operations are created on demand when those operations are used.
"""

# Revision identifiers, used by Alembic.
revision = "33d80081a422"
down_revision = "21363943d743"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
