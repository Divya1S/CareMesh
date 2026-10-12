"""auth session families

Refresh token rotation with reuse detection: every session belongs to a
family rooted at the login that created it. Presenting a token that was
already rotated revokes the whole family.

Revision ID: ededa2e5230b
Revises: d744ccf51ef9
Create Date: 2026-10-12 15:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "ededa2e5230b"
down_revision: str | None = "d744ccf51ef9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "auth_sessions",
        sa.Column("family_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    # Existing sessions become their own family root.
    op.execute("UPDATE auth_sessions SET family_id = id WHERE family_id IS NULL")
    op.alter_column("auth_sessions", "family_id", nullable=False)
    op.create_index("ix_auth_sessions_family", "auth_sessions", ["family_id"])


def downgrade() -> None:
    op.drop_index("ix_auth_sessions_family", table_name="auth_sessions")
    op.drop_column("auth_sessions", "family_id")
