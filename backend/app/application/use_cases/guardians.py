"""The guardian portal: guardians see exactly what the care team shares
about their explicitly linked students, and nothing else. No conversations,
no risk signals, no clinical records."""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from app.application.errors import ForbiddenError
from app.domain import events as domain_events
from app.domain.entities import Role, User


@dataclass(frozen=True, slots=True)
class GuardianOverview:
    students: list[dict]
    updates: list[dict]
    notifications: list[dict]


class GuardianService:
    def __init__(self, guardians, assignments, users, outbox) -> None:
        self._guardians = guardians
        self._assignments = assignments
        self._users = users
        self._outbox = outbox

    async def my_patients(self, actor: User) -> list[dict]:
        """The therapist's assigned patients, for the share update form."""
        if actor.role is not Role.THERAPIST:
            raise ForbiddenError("Only therapists have assigned patients")
        patient_ids = await self._assignments.patient_ids_for_therapist(
            actor.organization_id, actor.id
        )
        result = []
        for patient_id in patient_ids:
            patient = await self._users.get_by_id(patient_id)
            if patient:
                result.append({"patient_id": str(patient_id), "name": patient.display_name})
        return result

    async def overview(self, actor: User) -> GuardianOverview:
        if actor.role is not Role.GUARDIAN:
            raise ForbiddenError("Only guardians use the guardian portal")
        links = await self._guardians.links_for_guardian(actor.id)
        patient_ids = [patient_id for patient_id, _ in links]
        updates = await self._guardians.updates_for_patients(patient_ids) if patient_ids else []
        notifications = await self._guardians.notifications_for_guardian(actor.id)
        return GuardianOverview(
            students=[{"patient_id": str(patient_id), "name": name} for patient_id, name in links],
            updates=[
                {
                    "id": str(row.id),
                    "patient_name": patient_name,
                    "author_name": author_name,
                    "content": row.content,
                    "created_at": row.created_at.isoformat(),
                }
                for row, author_name, patient_name in updates
            ],
            notifications=[
                {
                    "id": str(row.id),
                    "kind": row.kind,
                    "content": row.content,
                    "created_at": row.created_at.isoformat(),
                }
                for row in notifications
            ],
        )

    async def share_update(
        self, actor: User, patient_id: UUID, content: str, correlation_id: str | None
    ) -> None:
        """A therapist deliberately writes an update for guardians. This is
        the only path by which care information reaches a guardian."""
        if actor.role is not Role.THERAPIST:
            raise ForbiddenError("Only therapists share guardian updates")
        if not await self._assignments.is_assigned(actor.id, patient_id):
            raise ForbiddenError("You are not assigned to this patient")
        now = datetime.now(UTC)
        await self._guardians.add_update(
            organization_id=actor.organization_id,
            patient_id=patient_id,
            author_id=actor.id,
            content=content.strip(),
            now=now,
        )
        for guardian_id in await self._guardians.guardians_for_patient(patient_id):
            notification_id = await self._guardians.add_notification(
                organization_id=actor.organization_id,
                guardian_id=guardian_id,
                patient_id=patient_id,
                kind="care_update",
                content="The care team shared a new update with you.",
                now=now,
            )
            await self._outbox.add(
                domain_events.guardian_notification_required(
                    notification_id=notification_id,
                    guardian_id=guardian_id,
                    patient_id=patient_id,
                    kind="care_update",
                    organization_id=actor.organization_id,
                    occurred_at=now,
                    correlation_id=correlation_id,
                )
            )
