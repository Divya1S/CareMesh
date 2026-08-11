"""Appointment requests raised through Dira, worked by the care team."""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from app.application.errors import DomainValidationError, ForbiddenError, NotFoundError
from app.domain.entities import Role, User
from app.domain.workflows import AppointmentRequestState, WorkflowType, validate_transition


@dataclass(frozen=True, slots=True)
class AppointmentRequestView:
    request_id: UUID
    workflow_id: UUID
    patient_name: str
    note: str
    state: str
    created_at: datetime


class AppointmentService:
    def __init__(self, appointments, workflows, assignments) -> None:
        self._appointments = appointments
        self._workflows = workflows
        self._assignments = assignments

    async def list_pending(self, actor: User) -> list[AppointmentRequestView]:
        self._ensure_therapist(actor)
        patient_ids = await self._assignments.patient_ids_for_therapist(
            actor.organization_id, actor.id
        )
        if not patient_ids:
            return []
        rows = await self._appointments.list_joined(
            actor.organization_id, patient_ids, AppointmentRequestState.REQUESTED.value
        )
        return [
            AppointmentRequestView(
                request_id=row.id,
                workflow_id=row.workflow_id,
                patient_name=name,
                note=row.note,
                state=state,
                created_at=row.created_at,
            )
            for row, state, name in rows
        ]

    async def acknowledge(self, actor: User, request_id: UUID) -> str:
        self._ensure_therapist(actor)
        request = await self._appointments.get_by_id(request_id)
        if request is None or request.organization_id != actor.organization_id:
            raise NotFoundError("Appointment request not found")
        if not await self._assignments.is_assigned(actor.id, request.patient_id):
            raise ForbiddenError("You are not assigned to this patient")
        workflow = await self._workflows.get_by_id(request.workflow_id)
        if workflow.state != AppointmentRequestState.REQUESTED:
            raise DomainValidationError("This request is already acknowledged")
        validate_transition(
            WorkflowType.APPOINTMENT_REQUEST,
            workflow.state,
            AppointmentRequestState.ACKNOWLEDGED,
        )
        await self._workflows.transition(
            workflow_id=workflow.id,
            from_state=workflow.state,
            to_state=AppointmentRequestState.ACKNOWLEDGED,
            actor=str(actor.id),
            reason="acknowledged by the care team",
            now=datetime.now(UTC),
        )
        return AppointmentRequestState.ACKNOWLEDGED.value

    @staticmethod
    def _ensure_therapist(actor: User) -> None:
        if actor.role is not Role.THERAPIST:
            raise ForbiddenError("Only therapists handle appointment requests")
