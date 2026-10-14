import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.google import GoogleAuthError, GoogleIdentity, verify_id_token
from app.auth.service import user_from_google
from app.models import User

CLIENT_ID = "test-client.apps.googleusercontent.com"


@pytest.fixture(scope="module")
def keypair() -> tuple[rsa.RSAPrivateKey, dict]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key(), as_dict=True)
    jwk["kid"] = "k1"
    return key, {"keys": [jwk]}


def _token(key: rsa.RSAPrivateKey, **overrides: object) -> str:
    now = int(time.time())
    claims = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "sub": "google-123",
        "email": "owner@example.com",
        "email_verified": True,
        "iat": now,
        "exp": now + 600,
        "nonce": "n1",
        **overrides,
    }
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "k1"})


def test_valid_id_token(keypair: tuple) -> None:
    key, jwks = keypair
    claims = verify_id_token(_token(key), jwks, CLIENT_ID, "n1")
    assert claims["sub"] == "google-123"


@pytest.mark.parametrize(
    "overrides",
    [
        {"aud": "someone-else"},
        {"iss": "https://evil.example"},
        {"nonce": "other"},
        {"exp": int(time.time()) - 10},
    ],
)
def test_invalid_id_tokens_are_rejected(keypair: tuple, overrides: dict) -> None:
    key, jwks = keypair
    with pytest.raises(GoogleAuthError):
        verify_id_token(_token(key, **overrides), jwks, CLIENT_ID, "n1")


def test_token_signed_by_unknown_key_is_rejected(keypair: tuple) -> None:
    _, jwks = keypair
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(GoogleAuthError):
        verify_id_token(_token(other), jwks, CLIENT_ID, "n1")


async def test_google_links_existing_account_only_when_verified(db: AsyncSession) -> None:
    db.add(User(email="owner@example.com", name="Owner", password_hash="x"))
    await db.commit()

    with pytest.raises(PermissionError):
        await user_from_google(db, GoogleIdentity("g1", "owner@example.com", email_verified=False, name=None))

    user = await user_from_google(
        db, GoogleIdentity("g1", "Owner@Example.com", email_verified=True, name=None)
    )
    await db.commit()
    assert user.google_sub == "g1"
    assert len((await db.scalars(select(User))).all()) == 1


async def test_google_creates_new_user(db: AsyncSession) -> None:
    user = await user_from_google(
        db, GoogleIdentity("g2", "new@example.com", email_verified=True, name="New")
    )
    await db.commit()
    assert user.name == "New" and user.password_hash is None
    again = await user_from_google(
        db, GoogleIdentity("g2", "changed@example.com", email_verified=True, name="x")
    )
    assert again.id == user.id
