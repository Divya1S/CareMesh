"""Workflow state machines (ADR 0004). Explicit states, explicit transitions,
append only history. No hidden background logic."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class WorkflowType(StrEnum):
    RISK_ESCALATION = "risk_escalation"
    REFERRAL = "referral"
    CLAIM = "claim"
    APPOINTMENT_REQUEST = "appointment_request"


class RiskEscalationState(StrEnum):
    PENDING_REVIEW = "pending_review"
    RESOLVED = "resolved"
    FAILED = "failed"


class ReferralState(StrEnum):
    SUBMITTED = "submitted"
    ACCEPTED = "accepted"
    DECLINED = "declined"


class ClaimState(StrEnum):
    SUBMITTED = "submitted"
    APPROVED = "approved"
    DENIED = "denied"
    RESUBMITTED = "resubmitted"


class AppointmentRequestState(StrEnum):
    REQUESTED = "requested"
    ACKNOWLEDGED = "acknowledged"


# Allowed transitions per workflow type. A transition not listed here is a
# bug, and attempting it raises instead of silently corrupting state.
TRANSITIONS_BY_TYPE: dict[WorkflowType, dict[str, frozenset[str]]] = {
    WorkflowType.RISK_ESCALATION: {
        RiskEscalationState.PENDING_REVIEW: frozenset(
            {RiskEscalationState.RESOLVED, RiskEscalationState.FAILED}
        ),
        RiskEscalationState.RESOLVED: frozenset(),
        RiskEscalationState.FAILED: frozenset(),
    },
    WorkflowType.REFERRAL: {
        ReferralState.SUBMITTED: frozenset({ReferralState.ACCEPTED, ReferralState.DECLINED}),
        ReferralState.ACCEPTED: frozenset(),
        ReferralState.DECLINED: frozenset(),
    },
    WorkflowType.CLAIM: {
        ClaimState.SUBMITTED: frozenset({ClaimState.APPROVED, ClaimState.DENIED}),
        ClaimState.DENIED: frozenset({ClaimState.RESUBMITTED}),
        ClaimState.RESUBMITTED: frozenset({ClaimState.APPROVED, ClaimState.DENIED}),
        ClaimState.APPROVED: frozenset(),
    },
    WorkflowType.APPOINTMENT_REQUEST: {
        AppointmentRequestState.REQUESTED: frozenset({AppointmentRequestState.ACKNOWLEDGED}),
        AppointmentRequestState.ACKNOWLEDGED: frozenset(),
    },
}


class InvalidTransitionError(Exception):
    pass


def validate_transition(workflow_type: WorkflowType, from_state: str, to_state: str) -> None:
    transitions = TRANSITIONS_BY_TYPE.get(workflow_type)
    if transitions is None:
        raise InvalidTransitionError(f"Unknown workflow type: {workflow_type}")
    allowed = transitions.get(from_state, frozenset())
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
