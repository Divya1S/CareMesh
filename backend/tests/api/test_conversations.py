import pytest

pytestmark = pytest.mark.integration


async def create_conversation(client, headers, title="Feeling stressed"):
    response = await client.post("/api/v1/conversations", json={"title": title}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


async def test_patient_creates_and_lists_own_conversations(client, seeded, auth_header):
    headers = await auth_header("patient@a.caremesh.org")
    conversation = await create_conversation(client, headers)
    listed = await client.get("/api/v1/conversations", headers=headers)
    assert listed.status_code == 200
    assert [c["id"] for c in listed.json()] == [conversation["id"]]


async def test_patient_posts_and_reads_messages(client, seeded, auth_header):
    headers = await auth_header("patient@a.caremesh.org")
    conversation = await create_conversation(client, headers)
    posted = await client.post(
        f"/api/v1/conversations/{conversation['id']}/messages",
        json={"content": "Hi, I had a rough week."},
        headers=headers,
    )
    assert posted.status_code == 201
    assert posted.json()["sender_type"] == "patient"

    messages = await client.get(
        f"/api/v1/conversations/{conversation['id']}/messages", headers=headers
    )
    assert messages.status_code == 200
    assert len(messages.json()) == 1


async def test_therapist_cannot_create_conversation(client, seeded, auth_header):
    headers = await auth_header("therapist@a.caremesh.org")
    response = await client.post("/api/v1/conversations", json={"title": "nope"}, headers=headers)
    assert response.status_code == 403


async def test_assigned_therapist_reads_and_replies(client, seeded, auth_header):
    patient_headers = await auth_header("patient@a.caremesh.org")
    conversation = await create_conversation(client, patient_headers)

    therapist_headers = await auth_header("therapist@a.caremesh.org")
    read = await client.get(
        f"/api/v1/conversations/{conversation['id']}", headers=therapist_headers
    )
    assert read.status_code == 200

    reply = await client.post(
        f"/api/v1/conversations/{conversation['id']}/messages",
        json={"content": "Thanks for sharing. I am here."},
        headers=therapist_headers,
    )
    assert reply.status_code == 201
    assert reply.json()["sender_type"] == "clinician"


async def test_unassigned_therapist_is_forbidden(client, seeded, auth_header):
    patient_headers = await auth_header("patient@a.caremesh.org")
    conversation = await create_conversation(client, patient_headers)

    other_headers = await auth_header("therapist2@a.caremesh.org")
    read = await client.get(f"/api/v1/conversations/{conversation['id']}", headers=other_headers)
    assert read.status_code == 403
    listed = await client.get("/api/v1/conversations", headers=other_headers)
    assert listed.status_code == 200
    assert listed.json() == []


async def test_other_patient_is_forbidden(client, seeded, auth_header):
    patient_headers = await auth_header("patient@a.caremesh.org")
    conversation = await create_conversation(client, patient_headers)

    other_headers = await auth_header("patient2@a.caremesh.org")
    response = await client.get(
        f"/api/v1/conversations/{conversation['id']}", headers=other_headers
    )
    assert response.status_code == 403


async def test_cross_tenant_access_reads_as_not_found(client, seeded, auth_header):
    patient_headers = await auth_header("patient@a.caremesh.org")
    conversation = await create_conversation(client, patient_headers)

    intruder_headers = await auth_header("patient@b.caremesh.org")
    response = await client.get(
        f"/api/v1/conversations/{conversation['id']}", headers=intruder_headers
    )
    assert response.status_code == 404


async def test_ops_admin_has_no_conversation_access(client, seeded, auth_header):
    headers = await auth_header("ops@a.caremesh.org")
    listed = await client.get("/api/v1/conversations", headers=headers)
    assert listed.status_code == 403


async def test_unauthenticated_requests_are_401(client, seeded):
    response = await client.get("/api/v1/conversations")
    assert response.status_code == 401
    assert response.headers.get("www-authenticate") == "Bearer"
