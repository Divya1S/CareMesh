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

    # The old refresh token is single use, so a replay must fail.
    replay = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert replay.status_code == 401

    # The rotated token still works.
    second = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": first.json()["refresh_token"]}
    )
    assert second.status_code == 200


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
