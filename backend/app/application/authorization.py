"""Resource level authorization policies.

Pure functions over domain entities so they are trivially unit testable.
Every use case must call the policy that matches its action. The frontend
hiding something is never the control.
"""

from app.application.errors import ForbiddenError, NotFoundError
from app.domain.entities import Conversation, Role, User


def ensure_same_org(actor: User, conversation: Conversation) -> None:
    # Cross tenant access is reported as not found so tenants cannot probe
    # for the existence of other tenants' resources.
    if actor.organization_id != conversation.organization_id:
        raise NotFoundError("Conversation not found")


def ensure_can_view_conversation(
    actor: User, conversation: Conversation, therapist_is_assigned: bool
) -> None:
    ensure_same_org(actor, conversation)
    if actor.role is Role.PATIENT and conversation.patient_id == actor.id:
        return
    if actor.role is Role.THERAPIST and therapist_is_assigned:
        return
    raise ForbiddenError("You are not authorized to view this conversation")


def ensure_can_post_message(
    actor: User, conversation: Conversation, therapist_is_assigned: bool
) -> None:
    # Same policy as viewing for S1. Kept separate because the policies
    # diverge later (for example read only supervisors).
    ensure_can_view_conversation(actor, conversation, therapist_is_assigned)


def ensure_can_create_conversation(actor: User) -> None:
    if actor.role is not Role.PATIENT:
        raise ForbiddenError("Only patients can start conversations")


def ensure_can_list_conversations(actor: User) -> None:
    if actor.role not in (Role.PATIENT, Role.THERAPIST):
        raise ForbiddenError("Your role has no access to conversations")
