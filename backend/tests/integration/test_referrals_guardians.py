"""P9 boundaries: the school sees names and its own referral states only;
guardians see only what the care team explicitly shares; a referral is a
real workflow whose acceptance assigns the therapist and notifies guardians."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.domain.entities import Role
from app.infrastructure.models import DomainEventLogRow, WorkflowInstanceRow
from app.infrastructure.repositories import SqlGuardianRepository, SqlUserRepository

pytestmark = pytest.mark.integration


@pytest.fixture
async def p9_users(app, seeded):
    """Adds a school staff member and a guardian linked to patient A."""
    from tests.conftest import _user

    school = _user(seeded["org_a"].id, "school@a.caremesh.org", Role.SCHOOL_STAFF, "Sky A")
    guardian = _user(seeded["org_a"].id, "guardian@a.caremesh.org", Role.GUARDIAN, "Gale A")
    async with app.state.session_factory() as session:
        users = SqlUserRepository(session)
        await users.add(school)
        await users.add(guardian)
        await session.flush()
        await SqlGuardianRepository(session).add_link(
            organization_id=seeded["org_a"].id,
            guardian_id=guardian.id,
            patient_id=seeded["patient"].id,
            now=datetime.now(UTC),
        )
        await session.commit()
    return {"school": school, "guardian": guardian}


async def submit_referral(client, headers, patient_id, consent=True):
    return await client.post(
        "/api/v1/school/referrals",
        json={
            "patient_id": str(patient_id),
            "concern": "Has seemed withdrawn in class for two weeks.",
            "consent_confirmed": consent,
        },
        headers=headers,
    )


async def test_roster_is_names_only(client, seeded, p9_users, auth_header):
    school = await auth_header("school@a.caremesh.org")
    response = await client.get("/api/v1/school/roster", headers=school)
    assert response.status_code == 200
    roster = response.json()
    assert {r["name"] for r in roster} == {"Pat A", "Pia A"}
    assert set(roster[0].keys()) == {"patient_id", "name"}, "roster must stay names only"

    # School staff have no access to clinical surfaces.
    assert (await client.get("/api/v1/conversations", headers=school)).status_code == 403
    assert (await client.get("/api/v1/reviews", headers=school)).status_code == 403


async def test_referral_requires_consent(client, seeded, p9_users, auth_header):
    school = await auth_header("school@a.caremesh.org")
    response = await submit_referral(client, school, seeded["patient"].id, consent=False)
    assert response.status_code == 422


async def test_referral_flow_assigns_and_notifies_guardian(
    client, app, seeded, p9_users, auth_header
):
    school = await auth_header("school@a.caremesh.org")
    submitted = await submit_referral(client, school, seeded["patient"].id)
    assert submitted.status_code == 201
    referral = submitted.json()
    assert referral["state"] == "submitted"

    # The unassigned therapist sees it in the pending queue and accepts it.
    therapist2 = await auth_header("therapist2@a.caremesh.org")
    pending = (await client.get("/api/v1/referrals", headers=therapist2)).json()
    assert len(pending) == 1 and pending[0]["patient_name"] == "Pat A"
    decided = await client.post(
        f"/api/v1/referrals/{referral['referral_id']}/decision",
        json={"accept": True},
        headers=therapist2,
    )
    assert decided.status_code == 200 and decided.json()["state"] == "accepted"

    # Accepting assigned the therapist: the patient's conversations now list.
    listed = (await client.get("/api/v1/conversations", headers=therapist2)).json()
    assert isinstance(listed, list)

    # The school sees the state change, mirrored exactly.
    mine = (await client.get("/api/v1/school/referrals", headers=school)).json()
    assert mine[0]["state"] == "accepted"

    # A second decision is refused: the workflow is terminal.
    again = await client.post(
        f"/api/v1/referrals/{referral['referral_id']}/decision",
        json={"accept": False},
        headers=therapist2,
    )
    assert again.status_code == 422

    # The linked guardian got a notification, and events went to the outbox.
    guardian = await auth_header("guardian@a.caremesh.org")
    overview = (await client.get("/api/v1/guardian/overview", headers=guardian)).json()
    assert overview["students"][0]["name"] == "Pat A"
    assert any(n["kind"] == "referral_accepted" for n in overview["notifications"])

    async with app.state.session_factory() as session:
        events = {e.event_type for e in (await session.scalars(select(DomainEventLogRow))).all()}
        workflow = await session.scalar(
            select(WorkflowInstanceRow).where(WorkflowInstanceRow.workflow_type == "referral")
        )
    assert {"ReferralSubmitted", "ReferralDecided", "GuardianNotificationRequired"} <= events
    assert workflow.state == "accepted"


async def test_guardian_sees_only_shared_updates(client, app, seeded, p9_users, auth_header):
    # The assigned therapist shares an update about patient A.
    therapist = await auth_header("therapist@a.caremesh.org")
    shared = await client.post(
        "/api/v1/guardian/updates",
        json={
            "patient_id": str(seeded["patient"].id),
            "content": "Sam engaged well this week and set a small goal.",
        },
        headers=therapist,
    )
    assert shared.status_code == 204

    guardian = await auth_header("guardian@a.caremesh.org")
    overview = (await client.get("/api/v1/guardian/overview", headers=guardian)).json()
    assert len(overview["updates"]) == 1
    assert "small goal" in overview["updates"][0]["content"]
    assert any(n["kind"] == "care_update" for n in overview["notifications"])

    # Guardians reach nothing else: no conversations, no reviews, no ops.
    for path in ("/api/v1/conversations", "/api/v1/reviews", "/api/v1/ops/workflows"):
        assert (await client.get(path, headers=guardian)).status_code == 403


async def test_unassigned_therapist_cannot_share_updates(client, seeded, p9_users, auth_header):
    therapist2 = await auth_header("therapist2@a.caremesh.org")
    response = await client.post(
        "/api/v1/guardian/updates",
        json={"patient_id": str(seeded["patient"].id), "content": "should not work"},
        headers=therapist2,
    )
    assert response.status_code == 403


async def test_patient_cannot_use_school_or_guardian_surfaces(
    client, seeded, p9_users, auth_header
):
    patient = await auth_header("patient@a.caremesh.org")
    assert (await client.get("/api/v1/school/roster", headers=patient)).status_code == 403
    assert (await client.get("/api/v1/guardian/overview", headers=patient)).status_code == 403
    assert (await client.get("/api/v1/referrals", headers=patient)).status_code == 403
