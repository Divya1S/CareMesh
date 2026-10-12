import asyncio

import pytest

pytestmark = pytest.mark.integration


async def test_login_returns_token_pair(client, seeded, login):
    tokens = await login("patient@a.caremesh.org")
    assert tokens["token_type"] == "bearer"
    assert tokens["access_token"] and tokens["refresh_token"]


async def test_login_wrong_password_is_401_problem(client, seeded):
    response = await client.post(
        "/api/v1/auth/login", json={"email": "patient@a.caremesh.org", "password": "nope"}
    )
    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["title"] == "Unauthorized"


async def test_login_unknown_email_is_401(client, seeded):
    response = await client.post(
        "/api/v1/auth/login", json={"email": "ghost@a.caremesh.org", "password": "whatever"}
    )
    assert response.status_code == 401


async def test_me_requires_token(client, seeded):
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401


async def test_me_returns_profile(client, seeded, auth_header):
    headers = await auth_header("therapist@a.caremesh.org")
    response = await client.get("/api/v1/auth/me", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "therapist@a.caremesh.org"
    assert body["role"] == "therapist"


async def test_refresh_rotates_and_revokes_old_token(client, seeded, login):
    tokens = await login("patient@a.caremesh.org")
    first = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert first.status_code == 200
    assert first.json()["refresh_token"] != tokens["refresh_token"]

    # The rotated token works.
    second = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": first.json()["refresh_token"]}
    )
    assert second.status_code == 200

    # The old refresh token is single use, so a replay must fail. (Reuse
    # also revokes the whole family; that path has its own test below.)
    replay = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert replay.status_code == 401


async def test_access_token_rejected_as_refresh_token(client, seeded, login):
    tokens = await login("patient@a.caremesh.org")
    response = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["access_token"]}
    )
    assert response.status_code == 401


async def test_request_id_header_present(client, seeded):
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.headers.get("x-request-id")


async def test_reusing_a_rotated_refresh_token_revokes_the_family(client, seeded, login):
    """Stolen token scenario: the thief refreshes first and holds a valid
    pair. When the real client presents the old token, reuse is detected
    and the whole family dies, including the thief's new token."""
    first = await login("patient@a.caremesh.org")
    second = (
        await client.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    ).json()

    reuse = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]}
    )
    assert reuse.status_code == 401
    assert "already used" in reuse.json()["detail"]

    thief = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": second["refresh_token"]}
    )
    assert thief.status_code == 401, "the family was revoked"

    # A fresh login starts a new family and works normally.
    again = await login("patient@a.caremesh.org")
    ok = await client.post("/api/v1/auth/refresh", json={"refresh_token": again["refresh_token"]})
    assert ok.status_code == 200


async def test_concurrent_refreshes_with_one_token_let_exactly_one_win(client, seeded, login):
    first = await login("patient@a.caremesh.org")
    body = {"refresh_token": first["refresh_token"]}
    a, b = await asyncio.gather(
        client.post("/api/v1/auth/refresh", json=body),
        client.post("/api/v1/auth/refresh", json=body),
    )
    assert sorted([a.status_code, b.status_code]) == [200, 401]
