"""review queue and appointment indexes

The pending review query joins workflow_instances.subject_id to
risk_signals.id, and the appointment idempotency check filters on
appointment_requests.conversation_id. Neither column was indexed.

Revision ID: 601c3bf9590b
Revises: ededa2e5230b
Create Date: 2026-10-12 15:05:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "601c3bf9590b"
down_revision: str | None = "ededa2e5230b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_workflow_instances_subject", "workflow_instances", ["subject_id"])
    op.create_index(
        "ix_appointment_requests_conversation", "appointment_requests", ["conversation_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_appointment_requests_conversation", table_name="appointment_requests")
    op.drop_index("ix_workflow_instances_subject", table_name="workflow_instances")
