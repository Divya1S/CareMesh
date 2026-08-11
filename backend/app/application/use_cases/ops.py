"""Ops console use cases: inspect workflows, AI requests, and the outbox,
and replay events safely. Read only except for event republish, which is
safe because every consumer is idempotent by event id."""

from uuid import UUID

from app.application.errors import ForbiddenError, NotFoundError
from app.domain.entities import Role, User


def ensure_ops(actor: User) -> None:
    if actor.role is not Role.OPS_ADMIN:
        raise ForbiddenError("Only operations admins can use the ops console")


class OpsService:
    def __init__(self, workflows, ai_requests, events) -> None:
        self._workflows = workflows
        self._ai_requests = ai_requests
        self._events = events

    async def list_workflows(self, actor: User, state: str | None, limit: int):
        ensure_ops(actor)
        return await self._workflows.list_for_org(actor.organization_id, state, limit)

    async def workflow_detail(self, actor: User, workflow_id: UUID):
        ensure_ops(actor)
        workflow = await self._workflows.get_by_id(workflow_id)
        if workflow is None or workflow.organization_id != actor.organization_id:
            raise NotFoundError("Workflow not found")
        transitions = await self._workflows.transitions_for(workflow_id)
        return workflow, transitions

    async def list_ai_requests(self, actor: User, limit: int):
        ensure_ops(actor)
        return await self._ai_requests.list_for_org(actor.organization_id, limit)

    async def ai_request_detail(self, actor: User, request_id: UUID):
        ensure_ops(actor)
        row = await self._ai_requests.get_for_org(actor.organization_id, request_id)
        if row is None:
            raise NotFoundError("AI request not found")
        return row

    async def list_events(self, actor: User, limit: int):
        ensure_ops(actor)
        return await self._events.list_for_org(actor.organization_id, limit)

    async def republish_event(self, actor: User, event_id: UUID) -> None:
        """Clears published_at so the relay publishes the event again.
        Safe by design: consumers skip duplicates by event id."""
        ensure_ops(actor)
        event = await self._events.get_for_org(actor.organization_id, event_id)
        if event is None:
            raise NotFoundError("Event not found")
        await self._events.mark_unpublished(event_id)
