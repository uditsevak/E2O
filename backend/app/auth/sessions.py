from datetime import UTC, datetime, timedelta

from fastapi import Request, Response
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.security import hash_token, new_token
from app.models import AuthSession, User

_TOUCH_EVERY = timedelta(hours=1)


async def start_session(db: AsyncSession, user: User, request: Request, response: Response) -> None:
    settings = get_settings()
    token = new_token()
    now = datetime.now(UTC)
    db.add(
        AuthSession(
            user_id=user.id,
            token_hash=hash_token(token),
            expires_at=now + timedelta(days=settings.session_ttl_days),
            last_seen_at=now,
            user_agent=(request.headers.get("user-agent") or "")[:500] or None,
            ip=request.client.host if request.client else None,
        )
    )
    user.last_login_at = now
    set_session_cookie(response, token)


def set_session_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        settings.session_cookie_name,
        token,
        max_age=settings.session_ttl_days * 24 * 3600,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        settings.session_cookie_name,
        path="/",
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
    )


async def resolve_session(db: AsyncSession, token: str | None) -> AuthSession | None:
    if not token:
        return None
    session = await db.scalar(select(AuthSession).where(AuthSession.token_hash == hash_token(token)))
    if session is None:
        return None
    now = datetime.now(UTC)
    if session.expires_at <= now:
        await db.delete(session)
        await db.commit()
        return None
    if now - session.last_seen_at > _TOUCH_EVERY:
        session.last_seen_at = now
        await db.commit()
    return session


async def end_session(db: AsyncSession, token: str | None) -> None:
    if token:
        await db.execute(delete(AuthSession).where(AuthSession.token_hash == hash_token(token)))
        await db.commit()
