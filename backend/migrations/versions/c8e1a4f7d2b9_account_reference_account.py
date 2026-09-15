"""Add account reference_account_id.

Revision ID: c8e1a4f7d2b9
Revises: b4d8f1a6c2e7
Create Date: 2026-07-25 09:00:00.000000

Adds reference_account_id to accounts (specification §4.2, §5.2). Investment accounts
contain security positions without their own cash. Cash movements from trades and income
events affect the linked reference account, such as the checking account used to
purchase securities.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "c8e1a4f7d2b9"
down_revision = "b4d8f1a6c2e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("accounts") as batch_op:
        batch_op.add_column(sa.Column("reference_account_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_accounts_reference_account_id", "accounts", ["reference_account_id"], ["id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("accounts") as batch_op:
        batch_op.drop_constraint("fk_accounts_reference_account_id", type_="foreignkey")
        batch_op.drop_column("reference_account_id")
