"""add referral workflow type

Revision ID: 840af87195a6
Revises: 6245b76ab2c3
Create Date: 2026-08-10 19:21:02.316153

"""

from collections.abc import Sequence

from alembic import op

revision: str = "840af87195a6"
down_revision: str | None = "6245b76ab2c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Alembic autogenerate does not detect enum member additions.
    op.execute("ALTER TYPE workflow_type ADD VALUE IF NOT EXISTS 'REFERRAL'")


def downgrade() -> None:
    # Postgres cannot remove an enum value; harmless to leave in place.
    pass
