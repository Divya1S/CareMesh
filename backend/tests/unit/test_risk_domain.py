import pytest

from app.domain.risk import RiskCategory, escalation_required
from app.domain.workflows import (
    InvalidTransitionError,
    RiskEscalationState,
    WorkflowType,
    validate_transition,
)


def test_crisis_and_self_harm_always_escalate():
    assert escalation_required(RiskCategory.CRISIS, 0)
    assert escalation_required(RiskCategory.SELF_HARM, 1)


def test_severity_threshold_escalates():
    assert escalation_required(RiskCategory.LOW_MOOD, 2)
    assert escalation_required(RiskCategory.ANXIETY, 3)


def test_low_severity_does_not_escalate():
    assert not escalation_required(RiskCategory.NONE, 0)
    assert not escalation_required(RiskCategory.LOW_MOOD, 1)


def test_valid_transition_passes():
    validate_transition(
        WorkflowType.RISK_ESCALATION,
        RiskEscalationState.PENDING_REVIEW,
        RiskEscalationState.RESOLVED,
    )


def test_resolved_is_terminal():
    with pytest.raises(InvalidTransitionError):
        validate_transition(
            WorkflowType.RISK_ESCALATION,
            RiskEscalationState.RESOLVED,
            RiskEscalationState.PENDING_REVIEW,
        )


def test_unknown_state_is_rejected():
    with pytest.raises(InvalidTransitionError):
        validate_transition(WorkflowType.RISK_ESCALATION, "nonsense", "resolved")
