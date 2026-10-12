"""The three concurrency primitives the audit added, tested at the
repository level where the outcome cannot be explained by a sequential
state check: a stale writer loses the compare and swap, a second revoke
of one session loses, and the appointment check blocks behind the lock.
"""

import asyncio
from datetime import UTC, datetime

import pytest

from app.application.errors import ConflictError
from app.domain.entities import AuthSession, Conversation
from app.domain.ids import uuid7
from app.domain.workflows import RiskEscalationState, WorkflowType
from app.infrastructure.repositories import (
    SqlAppointmentRepository,
    SqlAuthSessionRepository,
    SqlConversationRepository,
    SqlWorkflowRepository,
)

pytestmark = pytest.mark.integration


async def test_stale_transition_loses_the_compare_and_swap(app, seeded):
    now = datetime.now(UTC)
    workflow_id = uuid7()
    async with app.state.session_factory() as session:
        await SqlWorkflowRepository(session).create(
            workflow_id=workflow_id,
            organization_id=seeded["org_a"].id,
            workflow_type=WorkflowType.RISK_ESCALATION,
            state=RiskEscalationState.PENDING_REVIEW,
            subject_id=uuid7(),
            correlation_id=None,
            reason="test",
            now=now,
        )
        await session.commit()

    # Two writers read the same pending state (no explicit state check in
    # between, unlike the use cases). The first moves it; the second holds
    # a stale from_state and must lose at the database, not just in code.
    async with app.state.session_factory() as first, app.state.session_factory() as second:
        stale_state = (await SqlWorkflowRepository(second).get_by_id(workflow_id)).state
        await SqlWorkflowRepository(first).transition(
            workflow_id=workflow_id,
            from_state=RiskEscalationState.PENDING_REVIEW,
            to_state=RiskEscalationState.RESOLVED,
            actor="first",
            reason="won",
            now=now,
        )
        await first.commit()
        with pytest.raises(ConflictError):
            await SqlWorkflowRepository(second).transition(
                workflow_id=workflow_id,
                from_state=stale_state,
                to_state=RiskEscalationState.FAILED,
                actor="second",
                reason="lost",
                now=now,
            )
        await second.rollback()

    async with app.state.session_factory() as session:
        transitions = await SqlWorkflowRepository(session).transitions_for(workflow_id)
    assert [t.to_state for t in transitions] == ["pending_review", "resolved"]


async def test_second_revoke_of_one_session_loses(app, seeded):
    now = datetime.now(UTC)
    session_id = uuid7()
    async with app.state.session_factory() as session:
        await SqlAuthSessionRepository(session).add(
            AuthSession(
                id=session_id,
                user_id=seeded["patient"].id,
                token_hash="h" * 64,
                expires_at=now,
                created_at=now,
                family_id=session_id,
            )
        )
        await session.commit()
    async with app.state.session_factory() as session:
        sessions = SqlAuthSessionRepository(session)
        assert await sessions.revoke_if_active(session_id, revoked_at=now) is True
        assert await sessions.revoke_if_active(session_id, revoked_at=now) is False
        await session.commit()


async def test_appointment_check_blocks_behind_the_conversation_lock(app, seeded):
    """Writer A takes the check (and the lock) and has not committed yet.
    Writer B's check must wait, then see A's committed request."""
    from app.domain.workflows import AppointmentRequestState

    now = datetime.now(UTC)
    conversation = Conversation(
        id=uuid7(),
        organization_id=seeded["org_a"].id,
        patient_id=seeded["patient"].id,
        title="lock",
        created_at=now,
    )
    async with app.state.session_factory() as session:
        await SqlConversationRepository(session).add(conversation)
        await session.commit()

    state = AppointmentRequestState.REQUESTED.value
    async with app.state.session_factory() as a, app.state.session_factory() as b:
        assert (
            await SqlAppointmentRepository(a).has_open_for_conversation(conversation.id, state)
            is False
        )
        b_check = asyncio.create_task(
            SqlAppointmentRepository(b).has_open_for_conversation(conversation.id, state)
        )
        await asyncio.sleep(0.3)
        assert not b_check.done(), "B must block until A's transaction ends"

        workflow_id = uuid7()
        await SqlWorkflowRepository(a).create(
            workflow_id=workflow_id,
            organization_id=conversation.organization_id,
            workflow_type=WorkflowType.APPOINTMENT_REQUEST,
            state=AppointmentRequestState.REQUESTED,
            subject_id=uuid7(),
            correlation_id=None,
            reason="test",
            now=now,
        )
        await SqlAppointmentRepository(a).add(
            request_id=uuid7(),
            organization_id=conversation.organization_id,
            patient_id=conversation.patient_id,
            conversation_id=conversation.id,
            workflow_id=workflow_id,
            note="",
            created_at=now,
        )
        await a.commit()
        assert await asyncio.wait_for(b_check, timeout=5) is True
        await b.rollback()
