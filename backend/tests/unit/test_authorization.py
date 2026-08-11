from datetime import UTC, datetime

import pytest

from app.application import authorization as authz
from app.application.errors import ForbiddenError, NotFoundError
from app.domain.entities import Conversation, Role, User
from app.domain.ids import uuid7

NOW = datetime.now(UTC)
ORG_A = uuid7()
ORG_B = uuid7()


def make_user(role: Role, org_id=ORG_A) -> User:
    return User(
        id=uuid7(),
        organization_id=org_id,
        email=f"{uuid7()}@test",
        password_hash="x",
        role=role,
        display_name="Test",
        is_active=True,
        created_at=NOW,
    )


def make_conversation(patient: User) -> Conversation:
    return Conversation(
        id=uuid7(),
        organization_id=patient.organization_id,
        patient_id=patient.id,
        title="t",
        created_at=NOW,
    )


def test_patient_can_view_own_conversation():
    patient = make_user(Role.PATIENT)
    authz.ensure_can_view_conversation(patient, make_conversation(patient), False)


def test_patient_cannot_view_other_patients_conversation():
    other = make_user(Role.PATIENT)
    with pytest.raises(ForbiddenError):
        authz.ensure_can_view_conversation(make_user(Role.PATIENT), make_conversation(other), False)


def test_assigned_therapist_can_view():
    patient = make_user(Role.PATIENT)
    authz.ensure_can_view_conversation(
        make_user(Role.THERAPIST), make_conversation(patient), therapist_is_assigned=True
    )


def test_unassigned_therapist_cannot_view():
    patient = make_user(Role.PATIENT)
    with pytest.raises(ForbiddenError):
        authz.ensure_can_view_conversation(
            make_user(Role.THERAPIST), make_conversation(patient), therapist_is_assigned=False
        )


def test_cross_tenant_reads_as_not_found():
    patient = make_user(Role.PATIENT, org_id=ORG_A)
    intruder = make_user(Role.PATIENT, org_id=ORG_B)
    with pytest.raises(NotFoundError):
        authz.ensure_can_view_conversation(intruder, make_conversation(patient), False)


def test_only_patients_create_conversations():
    authz.ensure_can_create_conversation(make_user(Role.PATIENT))
    for role in (Role.THERAPIST, Role.OPS_ADMIN, Role.GUARDIAN):
        with pytest.raises(ForbiddenError):
            authz.ensure_can_create_conversation(make_user(role))


def test_roles_without_conversation_access_are_rejected():
    for role in (Role.OPS_ADMIN, Role.GUARDIAN, Role.SCHOOL_STAFF, Role.PAYER_STAFF):
        with pytest.raises(ForbiddenError):
            authz.ensure_can_list_conversations(make_user(role))
