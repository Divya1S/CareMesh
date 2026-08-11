"""P10: the claim lifecycle as a real state machine with a labeled fake
payer adapter, denial tracking, and strict role boundaries."""

import pytest
from sqlalchemy import select

from app.infrastructure.models import DomainEventLogRow
from app.infrastructure.payer.fake_payer import FakePayerAdapter

pytestmark = pytest.mark.integration


def test_fake_payer_adapter_is_deterministic_and_labeled():
    adapter = FakePayerAdapter()
    good = adapter.check_eligibility("EVG-12345")
    assert good.eligible is True and good.plan_name and good.simulated is True
    bad = adapter.check_eligibility("evg-INELIG-9")
    assert bad.eligible is False and bad.simulated is True
    assert adapter.check_eligibility("EVG-12345") == good


async def check_eligibility(client, headers, member_id="EVG-1001"):
    response = await client.post(
        "/api/v1/claims/eligibility", json={"member_id": member_id}, headers=headers
    )
    assert response.status_code == 200
    return response.json()


async def submit_claim(client, headers, patient_id, check_id):
    return await client.post(
        "/api/v1/claims",
        json={
            "patient_id": str(patient_id),
            "description": "Therapy session, 50 minutes",
            "amount_cents": 12000,
            "eligibility_check_id": check_id,
        },
        headers=headers,
    )


@pytest.fixture
async def payer_headers(app, seeded, auth_header):
    from app.domain.entities import Role
    from app.infrastructure.repositories import SqlUserRepository
    from tests.conftest import _user

    payer = _user(seeded["org_a"].id, "payer@a.caremesh.org", Role.PAYER_STAFF, "Pay A")
    async with app.state.session_factory() as session:
        await SqlUserRepository(session).add(payer)
        await session.commit()
    return await auth_header("payer@a.caremesh.org")


async def test_claim_requires_eligibility_and_assignment(client, seeded, auth_header):
    therapist = await auth_header("therapist@a.caremesh.org")
    ineligible = await check_eligibility(client, therapist, "EVG-INELIG-1")
    assert ineligible["eligible"] is False and ineligible["simulated"] is True
    rejected = await submit_claim(
        client, therapist, seeded["patient"].id, ineligible["eligibility_check_id"]
    )
    assert rejected.status_code == 422

    eligible = await check_eligibility(client, therapist)
    unassigned = await submit_claim(
        client, therapist, seeded["patient2"].id, eligible["eligibility_check_id"]
    )
    assert unassigned.status_code == 403


async def test_claim_lifecycle_deny_resubmit_approve(
    client, app, seeded, auth_header, payer_headers
):
    therapist = await auth_header("therapist@a.caremesh.org")
    check = await check_eligibility(client, therapist)
    submitted = await submit_claim(
        client, therapist, seeded["patient"].id, check["eligibility_check_id"]
    )
    assert submitted.status_code == 201
    claim = submitted.json()
    assert claim["state"] == "submitted" and claim["plan_name"]

    # Denial without a reason is refused; with a reason it is tracked.
    no_reason = await client.post(
        f"/api/v1/claims/{claim['claim_id']}/decision",
        json={"approve": False},
        headers=payer_headers,
    )
    assert no_reason.status_code == 422
    denied = await client.post(
        f"/api/v1/claims/{claim['claim_id']}/decision",
        json={"approve": False, "denial_reason": "Missing session duration code"},
        headers=payer_headers,
    )
    assert denied.json()["state"] == "denied"

    listed = (await client.get("/api/v1/claims", headers=payer_headers)).json()
    assert listed[0]["denial_reason"] == "Missing session duration code"

    # The submitting therapist resubmits with a note; the payer approves.
    resubmitted = await client.post(
        f"/api/v1/claims/{claim['claim_id']}/resubmit",
        json={"note": "Added duration code 90834"},
        headers=therapist,
    )
    assert resubmitted.json()["state"] == "resubmitted"
    approved = await client.post(
        f"/api/v1/claims/{claim['claim_id']}/decision",
        json={"approve": True},
        headers=payer_headers,
    )
    assert approved.json()["state"] == "approved"

    # Approved is terminal.
    again = await client.post(
        f"/api/v1/claims/{claim['claim_id']}/decision",
        json={"approve": False, "denial_reason": "x"},
        headers=payer_headers,
    )
    assert again.status_code == 422

    # The history rail shows every transition, actor attributed.
    history = (
        await client.get(f"/api/v1/claims/{claim['claim_id']}/history", headers=payer_headers)
    ).json()
    assert [t["to_state"] for t in history] == [
        "submitted",
        "denied",
        "resubmitted",
        "approved",
    ]
    assert history[1]["reason"] == "Missing session duration code"

    async with app.state.session_factory() as session:
        events = [e.event_type for e in (await session.scalars(select(DomainEventLogRow))).all()]
    assert events.count("InsuranceClaimSubmitted") == 1
    assert events.count("InsuranceClaimUpdated") == 3


async def test_claim_role_boundaries(client, seeded, auth_header, payer_headers):
    therapist = await auth_header("therapist@a.caremesh.org")
    check = await check_eligibility(client, therapist)
    claim = (
        await submit_claim(client, therapist, seeded["patient"].id, check["eligibility_check_id"])
    ).json()

    # Therapists cannot decide; payers cannot submit or resubmit.
    assert (
        await client.post(
            f"/api/v1/claims/{claim['claim_id']}/decision",
            json={"approve": True},
            headers=therapist,
        )
    ).status_code == 403
    assert (
        await client.post(
            "/api/v1/claims/eligibility", json={"member_id": "X-1"}, headers=payer_headers
        )
    ).status_code == 403

    # Another therapist sees no claims of colleagues and cannot resubmit them.
    other = await auth_header("therapist2@a.caremesh.org")
    assert (await client.get("/api/v1/claims", headers=other)).json() == []

    # Patients and payer staff stay out of clinical surfaces.
    patient = await auth_header("patient@a.caremesh.org")
    assert (await client.get("/api/v1/claims", headers=patient)).status_code == 403
    assert (await client.get("/api/v1/conversations", headers=payer_headers)).status_code == 403
    assert (await client.get("/api/v1/reviews", headers=payer_headers)).status_code == 403
