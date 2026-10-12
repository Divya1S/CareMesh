"""risk signal ai request optional

The deterministic crisis phrase floor can now open a review workflow when
the model is unavailable. Such a signal has no AI request behind it.

Revision ID: d744ccf51ef9
Revises: 8b6cb465d1ab
Create Date: 2026-10-12 13:10:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d744ccf51ef9"
down_revision: str | None = "8b6cb465d1ab"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "risk_signals",
        "ai_request_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
    )


def downgrade() -> None:
    # Floor only signals have no AI request. They are append only clinical
    # records, so refuse rather than delete or fail halfway.
    nulls = (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM risk_signals WHERE ai_request_id IS NULL"))
        .scalar_one()
    )
    if nulls:
        raise RuntimeError(
            f"{nulls} risk_signals rows have no ai_request_id (crisis phrase floor); "
            "this downgrade would drop them. Resolve them first."
        )
    op.alter_column(
        "risk_signals",
        "ai_request_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )
