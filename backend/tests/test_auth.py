import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import AuthSession, User
from tests.conftest import ClientFactory, signup


async def test_signup_starts_a_session(client: httpx.AsyncClient) -> None:
    user = await signup(client, "Owner@DCEngineering.in", name="Ramesh")
    assert user["email"] == "owner@dcengineering.in"
    assert user["has_password"] is True

    cookie = client.cookies.get(get_settings().session_cookie_name)
    assert cookie

    me = await client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["name"] == "Ramesh"
    assert me.json()["workspaces"] == []


async def test_session_token_is_stored_hashed(client: httpx.AsyncClient, db: AsyncSession) -> None:
    await signup(client, "a@example.com")
    token = client.cookies.get(get_settings().session_cookie_name)
    stored = (await db.scalars(select(AuthSession.token_hash))).all()
    assert len(stored) == 1
    assert token not in stored
    assert len(stored[0]) == 64


async def test_password_is_hashed(client: httpx.AsyncClient, db: AsyncSession) -> None:
    await signup(client, "a@example.com", password="correct-horse")
    user = await db.scalar(select(User))
    assert user is not None and user.password_hash
    assert "correct-horse" not in user.password_hash
    assert user.password_hash.startswith("$argon2")


async def test_duplicate_email_is_rejected(make_client: ClientFactory) -> None:
    await signup(make_client(), "a@example.com")
    resp = await make_client().post(
        "/api/auth/signup", json={"email": "A@example.com", "name": "x", "password": "another-password"}
    )
    assert resp.status_code == 409


async def test_short_password_is_rejected(client: httpx.AsyncClient) -> None:
    resp = await client.post(
        "/api/auth/signup", json={"email": "a@example.com", "name": "x", "password": "short"}
    )
    assert resp.status_code == 422


async def test_login_and_logout(make_client: ClientFactory) -> None:
    await signup(make_client(), "a@example.com", password="correct-horse")

    client = make_client()
    bad = await client.post("/api/auth/login", json={"email": "a@example.com", "password": "wrong-password"})
    assert bad.status_code == 401
    unknown = await client.post(
        "/api/auth/login", json={"email": "nobody@example.com", "password": "whatever1"}
    )
    assert unknown.status_code == 401
    assert bad.json()["detail"] == unknown.json()["detail"]  # no account enumeration via login

    ok = await client.post("/api/auth/login", json={"email": "A@Example.com", "password": "correct-horse"})
    assert ok.status_code == 200
    assert (await client.get("/api/auth/me")).status_code == 200

    out = await client.post("/api/auth/logout")
    assert out.status_code == 204
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_logout_revokes_the_session_server_side(make_client: ClientFactory) -> None:
    client = make_client()
    await signup(client, "a@example.com")
    token = client.cookies.get(get_settings().session_cookie_name)
    await client.post("/api/auth/logout")

    replay = make_client()
    replay.cookies.set(get_settings().session_cookie_name, token)
    assert (await replay.get("/api/auth/me")).status_code == 401


async def test_unauthenticated_requests_are_rejected(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/auth/me")).status_code == 401
    assert (await client.post("/api/workspaces", json={"name": "x"})).status_code == 401


async def test_cross_site_writes_are_blocked(client: httpx.AsyncClient) -> None:
    await signup(client, "a@example.com")
    resp = await client.post(
        "/api/workspaces", json={"name": "x"}, headers={"Origin": "https://evil.example"}
    )
    assert resp.status_code == 403
    same_site = await client.post(
        "/api/workspaces", json={"name": "x"}, headers={"Origin": "http://testserver"}
    )
    assert same_site.status_code == 201


async def test_auth_config(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/auth/config")
    assert resp.json() == {"google_enabled": False}
    assert (await client.get("/api/auth/google/start")).status_code == 404


def test_safe_next_only_allows_relative_paths() -> None:
    from app.api.auth import safe_next

    assert safe_next("/w/123") == "/w/123"
    assert safe_next("https://evil.example") == "/"
    assert safe_next("//evil.example") == "/"
    assert safe_next("/\\evil.example") == "/"
    assert safe_next(None) == "/"
