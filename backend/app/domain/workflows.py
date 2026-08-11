"""Workflow state machines (ADR 0004). Explicit states, explicit transitions,
append only history. No hidden background logic."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class WorkflowType(StrEnum):
    RISK_ESCALATION = "risk_escalation"


class RiskEscalationState(StrEnum):
    PENDING_REVIEW = "pending_review"
    RESOLVED = "resolved"
    FAILED = "failed"


# Allowed transitions per workflow type. A transition not listed here is a
# bug, and attempting it raises instead of silently corrupting state.
RISK_ESCALATION_TRANSITIONS: dict[str, frozenset[str]] = {
    RiskEscalationState.PENDING_REVIEW: frozenset(
        {RiskEscalationState.RESOLVED, RiskEscalationState.FAILED}
    ),
    RiskEscalationState.RESOLVED: frozenset(),
    RiskEscalationState.FAILED: frozenset(),
}


class InvalidTransitionError(Exception):
    pass


def validate_transition(workflow_type: WorkflowType, from_state: str, to_state: str) -> None:
    if workflow_type is not WorkflowType.RISK_ESCALATION:
        raise InvalidTransitionError(f"Unknown workflow type: {workflow_type}")
    allowed = RISK_ESCALATION_TRANSITIONS.get(from_state, frozenset())
    if to_state not in allowed:
        raise InvalidTransitionError(f"{workflow_type}: cannot go from {from_state} to {to_state}")


@dataclass(frozen=True, slots=True)
class WorkflowInstance:
    id: UUID
    organization_id: UUID
    workflow_type: WorkflowType
    state: str
    # What this workflow is about; for risk escalation, the signal.
    subject_id: UUID
    correlation_id: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class WorkflowTransition:
    id: UUID
    workflow_id: UUID
    from_state: str | None
    to_state: str
    # A user id, or "system" for machine transitions.
    actor: str
    reason: str
    occurred_at: datetime
