"""Google sign-in for app users (OIDC authorization code flow with PKCE).

Scopes are only `openid email profile`. This has nothing to do with reading a Gmail mailbox,
which is a separate, per-connection OAuth grant.
"""

import base64
import hashlib
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt

from app.config import get_settings

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105 - a URL, not a secret
JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
ISSUERS = {"https://accounts.google.com", "accounts.google.com"}

STATE_COOKIE = "e2o_oauth"
STATE_TTL_SECONDS = 600


class GoogleAuthError(Exception):
    pass


@dataclass
class GoogleIdentity:
    sub: str
    email: str
    email_verified: bool
    name: str | None


def redirect_uri() -> str:
    return f"{get_settings().app_url.rstrip('/')}/api/auth/google/callback"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def build_authorization(next_path: str) -> tuple[str, str]:
    """Returns (url to send the browser to, signed state cookie value)."""
    settings = get_settings()
    assert settings.google_client_id
    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(48)
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "prompt": "select_account",
    }
    cookie = jwt.encode(
        {
            "state": state,
            "nonce": nonce,
            "verifier": verifier,
            "next": next_path,
            "exp": int(time.time()) + STATE_TTL_SECONDS,
        },
        settings.secret_key.get_secret_value(),
        algorithm="HS256",
    )
    return f"{AUTH_URL}?{urlencode(params)}", cookie


def read_state_cookie(cookie: str | None, state: str | None) -> dict[str, Any]:
    if not cookie or not state:
        raise GoogleAuthError("Sign-in session expired. Please try again.")
    try:
        data = jwt.decode(cookie, get_settings().secret_key.get_secret_value(), algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise GoogleAuthError("Sign-in session expired. Please try again.") from exc
    if not secrets.compare_digest(data.get("state", ""), state):
        raise GoogleAuthError("Sign-in could not be verified. Please try again.")
    return data


_jwks_cache: tuple[float, dict[str, Any]] | None = None


async def _jwks(client: httpx.AsyncClient) -> dict[str, Any]:
    global _jwks_cache
    if _jwks_cache and _jwks_cache[0] > time.time():
        return _jwks_cache[1]
    resp = await client.get(JWKS_URL, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    _jwks_cache = (time.time() + 3600, data)
    return data


async def exchange_code(code: str, verifier: str, nonce: str) -> GoogleIdentity:
    settings = get_settings()
    assert settings.google_client_id and settings.google_client_secret
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret.get_secret_value(),
                "redirect_uri": redirect_uri(),
                "grant_type": "authorization_code",
                "code_verifier": verifier,
            },
            timeout=10,
        )
        if resp.status_code != 200:
            raise GoogleAuthError("Google sign-in failed. Please try again.")
        id_token = resp.json().get("id_token")
        if not id_token:
            raise GoogleAuthError("Google sign-in failed. Please try again.")
        jwks = await _jwks(client)

    claims = verify_id_token(id_token, jwks, settings.google_client_id, nonce)
    return GoogleIdentity(
        sub=claims["sub"],
        email=claims["email"],
        email_verified=bool(claims.get("email_verified")),
        name=claims.get("name"),
    )


def verify_id_token(id_token: str, jwks: dict[str, Any], client_id: str, nonce: str) -> dict[str, Any]:
    try:
        kid = jwt.get_unverified_header(id_token).get("kid")
        key_data = next((k for k in jwks.get("keys", []) if k.get("kid") == kid), None)
        if key_data is None:
            raise GoogleAuthError("Google sign-in could not be verified.")
        claims = jwt.decode(
            id_token,
            jwt.PyJWK(key_data).key,
            algorithms=["RS256"],
            audience=client_id,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise GoogleAuthError("Google sign-in could not be verified.") from exc
    if claims.get("iss") not in ISSUERS:
        raise GoogleAuthError("Google sign-in could not be verified.")
    if not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
        raise GoogleAuthError("Google sign-in could not be verified.")
    if not claims.get("email"):
        raise GoogleAuthError("Your Google account has no email address.")
    return claims
